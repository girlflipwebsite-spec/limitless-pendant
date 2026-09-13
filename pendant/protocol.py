"""Pendant BLE protocol: message framing, command encoding, response decoding.

Safety note (see CLAUDE.md "Hard Safety Rules"): `create_command` only knows
how to build the small set of commands this project is allowed to send -
reading device info/status, syncing the clock, and downloading recordings.
It deliberately has no code path for factory reset, storage erase, rekeying,
or firmware update, even though those commands exist in the device's
protocol (proto/pendant.proto). Do not add them here without first stopping
and discussing it with the client, per the project plan.
"""

from datetime import datetime
from typing import Optional

from .proto_loader import pb, PROTOBUF_AVAILABLE

# Commands this tool is allowed to send. Keep this list in sync with the
# branches implemented in create_command().
ALLOWED_COMMANDS = frozenset(
    {"get_device_info", "get_device_status", "set_current_time", "download_flash_pages"}
)


class PendantProtocol:
    """Encodes commands and decodes responses for the Pendant BLE protocol."""

    def __init__(self) -> None:
        self.message_index = 0
        self._pending_fragments: dict[int, list[Optional[bytes]]] = {}

    def create_ble_message(self, payload: bytes) -> bytes:
        """Wrap a serialized protobuf payload in the BLE fragmentation envelope."""
        if not PROTOBUF_AVAILABLE:
            raise RuntimeError("protobuf module not available - see pendant/proto_loader.py")

        msg = pb.BLEMessageFromNativeToPendant()
        msg.index = self.message_index
        msg.ble_fragment_seq = 0
        msg.num_fragments = 1
        msg.payload = payload
        self.message_index += 1
        return msg.SerializeToString()

    def parse_ble_message(self, data: bytes) -> Optional[bytes]:
        """Unwrap a BLE notification, reassembling fragments as needed.

        Returns the complete inner payload once all fragments of a message
        have arrived, or None while still waiting on fragments.
        """
        if not PROTOBUF_AVAILABLE:
            raise RuntimeError("protobuf module not available - see pendant/proto_loader.py")

        msg = pb.BLEMessageFromPendantToNative()
        msg.ParseFromString(bytes(data))

        if msg.num_fragments == 1:
            return msg.payload

        fragments = self._pending_fragments.setdefault(msg.index, [None] * msg.num_fragments)
        fragments[msg.ble_fragment_seq] = msg.payload

        if all(f is not None for f in fragments):
            complete = b"".join(fragments)
            del self._pending_fragments[msg.index]
            return complete
        return None

    def create_command(self, cmd_type: str, **kwargs) -> bytes:
        """Build a ServerCommandMsg and wrap it for transmission.

        Raises ValueError for any command not in ALLOWED_COMMANDS.
        """
        if not PROTOBUF_AVAILABLE:
            raise RuntimeError("protobuf module not available - see pendant/proto_loader.py")
        if cmd_type not in ALLOWED_COMMANDS:
            raise ValueError(
                f"Refusing to build command {cmd_type!r}: not in the allowed, read-safe "
                f"command set {sorted(ALLOWED_COMMANDS)}. See CLAUDE.md Hard Safety Rules."
            )

        cmd = pb.ServerCommandMsg()
        request_data = pb.RequestData()
        request_data.request_id = self.message_index + 1
        cmd.request_data.CopyFrom(request_data)

        if cmd_type == "get_device_info":
            cmd.get_device_info.CopyFrom(pb.GetDeviceInfo())

        elif cmd_type == "get_device_status":
            cmd.get_device_status.CopyFrom(pb.GetDeviceStatus())

        elif cmd_type == "set_current_time":
            sct = pb.SetCurrentTime()
            sct.timestamp_ms = kwargs.get("timestamp_ms", int(datetime.now().timestamp() * 1000))
            cmd.set_current_time.CopyFrom(sct)

        elif cmd_type == "download_flash_pages":
            dl = pb.DownloadFlashPages()
            dl.batch_mode_enabled = kwargs.get("batch", True)
            dl.real_time_mode_enabled = kwargs.get("realtime", False)
            cmd.download_flash_pages.CopyFrom(dl)

        return self.create_ble_message(cmd.SerializeToString())

    def parse_response(self, payload: bytes) -> dict:
        """Parse a PendantAllMsg response into a plain dict."""
        if not PROTOBUF_AVAILABLE:
            raise RuntimeError("protobuf module not available - see pendant/proto_loader.py")

        msg = pb.PendantAllMsg()
        msg.ParseFromString(payload)

        content_type = msg.WhichOneof("content")
        result: dict = {"type": content_type}

        if content_type == "device_info":
            info = msg.device_info
            result.update(
                firmware_version=info.firmware_version,
                hardware_version=info.hardware_version,
                serial_number=info.serial_number,
                device_name=info.device_name,
            )

        elif content_type == "device_status":
            status = msg.device_status
            is_recording = (
                status.HasField("recording_status")
                and status.recording_status.recording_state == 1
            )
            storage_percent = 0
            if status.HasField("storage_state"):
                total = status.storage_state.total_capture_pages
                free = status.storage_state.free_capture_pages
                if total > 0:
                    storage_percent = round((total - free) / total * 100)
            result.update(
                is_recording=is_recording,
                storage_used_percent=storage_percent,
                wifi_connected=status.HasField("wifi_status") and status.wifi_status.connected,
            )

        elif content_type == "storage_buffer":
            buf = msg.storage_buffer
            result.update(
                session=buf.session,
                run=buf.run,
                seq=buf.seq,
                index=buf.index,
                flash_page=buf.flash_page,
                error=buf.flash_page_error,
            )

        elif content_type == "battery_status":
            bat = msg.battery_status
            result.update(
                level=bat.soc,
                charging=bat.state in (1, 4),  # CHARGING or FULL
                voltage=bat.voltage,
                state=bat.state,
            )

        elif content_type == "set_current_time_response":
            result["success"] = msg.set_current_time_response.success

        elif content_type == "button_status":
            result["pressed"] = msg.button_status.pressed

        if msg.HasField("response_data"):
            result["request_id"] = msg.response_data.request_id
            result["response_success"] = msg.response_data.success

        return result

    def extract_audio_from_flash_page(self, data: bytes) -> "FlashPageAudio":
        """Pull audio + timestamp metadata out of a serialized FlashPage.

        This never attempts decryption. If `encrypted_codec_beamforming_data`
        is populated, that's reported as encrypted_bytes so the caller can
        surface the Section 7.4 encryption finding - decrypting it requires a
        device rekey, which is a client decision point, not something this
        function does.
        """
        if not PROTOBUF_AVAILABLE:
            raise RuntimeError("protobuf module not available - see pendant/proto_loader.py")

        page = pb.FlashPage()
        page.ParseFromString(data)

        opus_data = bytearray()
        encrypted_bytes = 0
        chunks: list[ChunkInfo] = []

        for chunk in page.chunks:
            has_audio = chunk.HasField("audio_data")
            if not has_audio:
                continue

            audio = chunk.audio_data
            offset_before = len(opus_data)

            if audio.codec_beamforming_data:
                opus_data.extend(audio.codec_beamforming_data)
            if audio.codec_manual_beamforming_data:
                opus_data.extend(audio.codec_manual_beamforming_data)
            if audio.HasField("encrypted_codec_beamforming_data"):
                encrypted_bytes += len(audio.encrypted_codec_beamforming_data.ciphertext)

            chunks.append(
                ChunkInfo(
                    time_offset_ms=chunk.time_offset_ms,
                    audio_offset_bytes=offset_before,
                    audio_byte_length=len(opus_data) - offset_before,
                    is_encrypted=audio.HasField("encrypted_codec_beamforming_data"),
                )
            )

        return FlashPageAudio(
            absolute_timestamp_ms=page.absolute_timestamp_ms,
            boot_uptime_ms=page.boot_uptime_ms,
            opus_data=bytes(opus_data),
            encrypted_bytes=encrypted_bytes,
            chunks=chunks,
        )


class ChunkInfo:
    __slots__ = ("time_offset_ms", "audio_offset_bytes", "audio_byte_length", "is_encrypted")

    def __init__(self, time_offset_ms, audio_offset_bytes, audio_byte_length, is_encrypted):
        self.time_offset_ms = time_offset_ms
        self.audio_offset_bytes = audio_offset_bytes
        self.audio_byte_length = audio_byte_length
        self.is_encrypted = is_encrypted


class FlashPageAudio:
    """Result of extracting audio from one FlashPage."""

    __slots__ = (
        "absolute_timestamp_ms",
        "boot_uptime_ms",
        "opus_data",
        "encrypted_bytes",
        "chunks",
    )

    def __init__(self, absolute_timestamp_ms, boot_uptime_ms, opus_data, encrypted_bytes, chunks):
        self.absolute_timestamp_ms = absolute_timestamp_ms
        self.boot_uptime_ms = boot_uptime_ms
        self.opus_data = opus_data
        self.encrypted_bytes = encrypted_bytes
        self.chunks = chunks

    @property
    def is_encrypted(self) -> bool:
        return self.encrypted_bytes > 0

    @property
    def has_plaintext_audio(self) -> bool:
        return len(self.opus_data) > 0
