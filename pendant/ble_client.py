"""BLE client for talking to the Pendant, via bleak (cross-platform, uses
CoreBluetooth on macOS).

Pairing note (revised - see CLAUDE.md Section 7.2): the Pendant is a
BLE-only custom peripheral, not a classic Bluetooth device - it doesn't
implement the audio/HID profiles that would make it show up as something
you manually "pair" in System Settings > Bluetooth like a headset. The
client confirmed via Limitless's own support content that the device only
has an official flow through the mobile app, and the mobile app itself
never asks the user to pre-pair it in the phone's OS Bluetooth settings
either - it just connects over BLE from within the app.

So the expected flow here mirrors that: don't try to pre-pair via System
Settings first. Instead:

  1. `scan()` finds the device by BLE advertisement alone, no pairing needed
     for that.
  2. `connect()` opens a GATT connection. If the device requests encryption/
     bonding at that point (matching the Android app's `createBond()` call
     noted in PROTOCOL.md), CoreBluetooth should negotiate it transparently,
     possibly surfacing a one-time macOS pairing/passkey confirmation dialog
     - which the user should accept if it appears.

Whether this actually works end-to-end (and what, if anything, macOS asks
the user to confirm) is still unverified - that's exactly the Phase 1
finding to report back, not something to guess further at without real
hardware.

Everything here is read-only with respect to the device: it only ever sends
the commands in protocol.ALLOWED_COMMANDS (info/status/clock-sync/download).
"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .audio_store import DownloadedPage, RecordingAssembler, Recording, save_recording
from .config import AUDIO_DATA_CHAR_UUID, AUDIO_SERVICE_UUID, CONTROL_CHAR_UUID
from .protocol import PendantProtocol
from .sync_state import SyncState

# How long to wait after the last StorageBufferMsg page before deciding the
# download is finished. The protocol has no explicit "download complete"
# message (see PROTOCOL.md) so this is a heuristic - if real hardware shows a
# clearer end-of-download signal (e.g. a status message with 0% pending),
# switch to that instead once Phase 2 confirms it.
DOWNLOAD_IDLE_TIMEOUT_SEC = 5.0
CONNECT_SCAN_TIMEOUT_SEC = 10.0
COMMAND_RESPONSE_TIMEOUT_SEC = 15.0


@dataclass
class ScanResult:
    address: str
    name: Optional[str]
    rssi: Optional[int]
    is_pendant: bool
    match_reason: str


@dataclass
class SyncResult:
    pages_received: int = 0
    pages_new: int = 0
    pages_already_seen: int = 0
    recordings_saved: list[dict] = field(default_factory=list)
    any_encrypted: bool = False


class PendantClient:
    def __init__(self, address: str, log: Optional[Callable[[str], None]] = None):
        self.address = address
        self.protocol = PendantProtocol()
        self._client = None  # bleak.BleakClient, set on connect()
        self._log = log or (lambda msg: None)

        self._pending_single_response: Optional[asyncio.Future] = None
        self._awaited_response_type: Optional[str] = None
        self._battery_level: Optional[dict] = None
        self._download_pages: list[DownloadedPage] = []
        self._download_active = False
        self._last_page_at: Optional[float] = None

    async def _notification_handler(self, _sender, data: bytes) -> None:
        try:
            payload = self.protocol.parse_ble_message(data)
        except Exception as exc:
            self._log(f"  [warn] failed to parse BLE envelope: {exc}")
            return
        if payload is None:
            return  # waiting on more fragments

        try:
            response = self.protocol.parse_response(payload)
        except Exception as exc:
            self._log(f"  [warn] failed to parse response payload: {exc}")
            return

        rtype = response.get("type")

        if rtype == "battery_status":
            self._battery_level = response

        if rtype == "storage_buffer":
            self._last_page_at = asyncio.get_event_loop().time()
            error = response.get("error", 0)
            if error:
                self._log(f"  [warn] flash page reported error code {error}, skipping")
            else:
                audio = self.protocol.extract_audio_from_flash_page(response["flash_page"])
                self._download_pages.append(
                    DownloadedPage(
                        session=response["session"],
                        run=response["run"],
                        seq=response["seq"],
                        index=response["index"],
                        audio=audio,
                    )
                )

        if (
            self._pending_single_response is not None
            and not self._pending_single_response.done()
            and rtype == self._awaited_response_type
        ):
            self._pending_single_response.set_result(response)

    async def connect(self) -> bool:
        from bleak import BleakClient, BleakScanner

        self._log(f"Scanning for {self.address} ({CONNECT_SCAN_TIMEOUT_SEC}s)...")
        devices = await BleakScanner.discover(timeout=CONNECT_SCAN_TIMEOUT_SEC, return_adv=True)

        device = None
        for addr, (dev, _adv) in devices.items():
            if addr.upper() == self.address.upper():
                device = dev
                break

        if device is None:
            self._log(
                "Device not found during scan. Make sure it's powered on, awake (tap it), "
                "and not connected to a phone via the official Limitless app - only one "
                "central device can hold its BLE connection at a time."
            )
            return False

        self._client = BleakClient(device, timeout=20.0)
        await self._client.connect()

        if not self._client.is_connected:
            self._log("Connect attempt did not report success.")
            return False

        mtu = getattr(self._client, "mtu_size", None)
        self._log(f"Connected. MTU={mtu}")

        await self._client.start_notify(AUDIO_DATA_CHAR_UUID, self._notification_handler)
        return True

    async def disconnect(self) -> None:
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(AUDIO_DATA_CHAR_UUID)
            except Exception:
                pass
            await self._client.disconnect()

    async def _send(self, cmd_type: str, **kwargs) -> None:
        cmd = self.protocol.create_command(cmd_type, **kwargs)
        await self._client.write_gatt_char(CONTROL_CHAR_UUID, cmd, response=False)

    async def _request(self, cmd_type: str, awaited_response_type: str, **kwargs) -> dict:
        """Send a command and wait for the matching response type."""
        loop = asyncio.get_event_loop()
        self._pending_single_response = loop.create_future()
        self._awaited_response_type = awaited_response_type
        await self._send(cmd_type, **kwargs)
        try:
            return await asyncio.wait_for(
                self._pending_single_response, timeout=COMMAND_RESPONSE_TIMEOUT_SEC
            )
        finally:
            self._pending_single_response = None
            self._awaited_response_type = None

    async def get_info(self) -> dict:
        return await self._request("get_device_info", "device_info")

    async def get_status(self) -> dict:
        status = await self._request("get_device_status", "device_status")
        if self._battery_level:
            status["battery"] = self._battery_level
        return status

    async def sync_time(self) -> dict:
        return await self._request("set_current_time", "set_current_time_response")

    async def sync_recordings(self, sync_state: Optional[SyncState] = None) -> SyncResult:
        """Download all flash pages currently on the device, save any new
        recordings to disk organized by date, and update sync_state so
        already-downloaded pages aren't re-saved next time."""
        sync_state = sync_state or SyncState()
        self._download_pages = []
        self._last_page_at = None

        self._log("Downloading recordings (this can take a while for a full device)...")
        await self._send("download_flash_pages", batch=True, realtime=False)

        # Wait for the first page, then keep waiting until pages stop
        # arriving for DOWNLOAD_IDLE_TIMEOUT_SEC (see module docstring).
        loop = asyncio.get_event_loop()
        start = loop.time()
        while True:
            await asyncio.sleep(0.5)
            if self._download_pages and self._last_page_at is not None:
                if loop.time() - self._last_page_at > DOWNLOAD_IDLE_TIMEOUT_SEC:
                    break
            if loop.time() - start > 180:
                self._log("  [warn] download timed out waiting for pages")
                break

        result = SyncResult(pages_received=len(self._download_pages))
        assembler = RecordingAssembler()
        downloaded_at = datetime.now()

        for page in self._download_pages:
            if sync_state.is_new(page.key):
                result.pages_new += 1
                assembler.add_page(page)
                sync_state.mark_seen(page.key)
            else:
                result.pages_already_seen += 1

        for recording in assembler.finish():
            saved = save_recording(recording, downloaded_at=downloaded_at)
            result.recordings_saved.append(saved)
            if saved["is_encrypted"]:
                result.any_encrypted = True

        sync_state.last_sync_iso = downloaded_at.isoformat()
        sync_state.save()
        return result


async def scan_for_pendants(duration: float = 10.0) -> list[ScanResult]:
    from bleak import BleakScanner

    devices = await BleakScanner.discover(timeout=duration, return_adv=True)
    results = []
    for addr, (device, adv) in devices.items():
        name = device.name or (adv.local_name if adv else None)
        is_pendant = False
        reason = ""
        if name and "pendant" in name.lower():
            is_pendant, reason = True, "name match"
        elif adv and AUDIO_SERVICE_UUID.lower() in [str(u).lower() for u in (adv.service_uuids or [])]:
            is_pendant, reason = True, "advertises Pendant audio service UUID"
        results.append(
            ScanResult(
                address=addr,
                name=name,
                rssi=(adv.rssi if adv else None),
                is_pendant=is_pendant,
                match_reason=reason,
            )
        )
    return results
