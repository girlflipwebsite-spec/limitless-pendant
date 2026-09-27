"""Shared constants: BLE UUIDs, timestamps, and local storage paths."""

import os
from pathlib import Path

# Device addressing. On macOS, bleak identifies peripherals by a CoreBluetooth
# UUID (not a MAC address) - whatever this is set to, `pendant scan` will help
# you find it.
PENDANT_ADDRESS = os.environ.get("PENDANT_ADDRESS")

# BLE UUIDs (from the reverse-engineered protocol, see PROTOCOL.md)
AUDIO_SERVICE_UUID = "632de001-604c-446b-a80f-7963e950f3fb"
CONTROL_CHAR_UUID = "632de002-604c-446b-a80f-7963e950f3fb"   # Phone -> Pendant (write)
AUDIO_DATA_CHAR_UUID = "632de003-604c-446b-a80f-7963e950f3fb"  # Pendant -> Phone (notify)

PENDANT_SERVICE_UUIDS = {
    AUDIO_SERVICE_UUID: "Pendant Audio Service",
    "8d53dc1d-1db7-4cd3-868b-8a527460aa84": "Pendant Data Channel",
}
PENDANT_CHARACTERISTIC_UUIDS = {
    CONTROL_CHAR_UUID: "Control (write)",
    AUDIO_DATA_CHAR_UUID: "Audio Data (notify)",
    "da2e7828-fbce-4e01-ae9e-261174997c48": "Bidirectional Data",
}

# Standard Bluetooth SIG services/characteristics that may be exposed
# alongside the custom protocol - reading these can sometimes trigger BLE
# bonding automatically if they require encryption (see the "explore"
# command, and pendant-cli's PROTOCOL.md note that battery level is read
# from the standard service "reliably").
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"
BATTERY_LEVEL_CHAR_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
DEVICE_INFO_SERVICE_UUID = "0000180a-0000-1000-8000-00805f9b34fb"

KNOWN_STANDARD_UUIDS = {
    "00001800-0000-1000-8000-00805f9b34fb": "Generic Access (standard)",
    "00001801-0000-1000-8000-00805f9b34fb": "Generic Attribute (standard)",
    DEVICE_INFO_SERVICE_UUID: "Device Information (standard)",
    BATTERY_SERVICE_UUID: "Battery Service (standard)",
    BATTERY_LEVEL_CHAR_UUID: "Battery Level (standard)",
    "00002a29-0000-1000-8000-00805f9b34fb": "Manufacturer Name (standard)",
    "00002a24-0000-1000-8000-00805f9b34fb": "Model Number (standard)",
    "00002a25-0000-1000-8000-00805f9b34fb": "Serial Number (standard)",
    "00002a26-0000-1000-8000-00805f9b34fb": "Firmware Revision (standard)",
    "00002a27-0000-1000-8000-00805f9b34fb": "Hardware Revision (standard)",
}

# A timestamp below this is almost certainly device uptime / unsynced clock,
# not a real wall-clock time (Jan 1, 2020).
MIN_VALID_TIMESTAMP_MS = 1577836800000

# Local storage layout, all under the project root unless overridden.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("PENDANT_DATA_DIR", PROJECT_ROOT / "data"))
RECORDINGS_DIR = DATA_DIR / "recordings"       # recordings/<YYYY-MM-DD>/*.opus,*.wav
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"     # transcripts/<YYYY-MM-DD>.md
LOGS_DIR = DATA_DIR / "logs"                   # diagnostic logs to send back to the developer
SYNC_STATE_PATH = DATA_DIR / "sync_state.json"


def get_pendant_address() -> str:
    if not PENDANT_ADDRESS:
        raise RuntimeError(
            "PENDANT_ADDRESS environment variable is not set. "
            "Run `python -m pendant.cli scan` to find your device, then "
            "export PENDANT_ADDRESS=<address-or-uuid> before running other commands."
        )
    return PENDANT_ADDRESS
