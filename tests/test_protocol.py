import pytest

from pendant.protocol import PendantProtocol, ALLOWED_COMMANDS
from pendant.proto_loader import pb


def test_allowed_command_round_trips_through_ble_envelope():
    proto = PendantProtocol()
    wire_bytes = proto.create_command("get_device_status")

    envelope = pb.BLEMessageFromNativeToPendant()
    envelope.ParseFromString(wire_bytes)
    assert envelope.num_fragments == 1

    inner = pb.ServerCommandMsg()
    inner.ParseFromString(envelope.payload)
    assert inner.WhichOneof("content") == "get_device_status"


def test_disallowed_command_is_refused():
    proto = PendantProtocol()
    with pytest.raises(ValueError):
        proto.create_command("factory_reset_pendant")
    with pytest.raises(ValueError):
        proto.create_command("clear_pendant_storage")


def test_parse_ble_message_reassembles_fragments():
    proto = PendantProtocol()
    payload = b"hello pendant, this is a fragmented payload"
    mid = len(payload) // 2

    def make_fragment(seq, num, chunk):
        msg = pb.BLEMessageFromPendantToNative()
        msg.index = 7
        msg.ble_fragment_seq = seq
        msg.num_fragments = num
        msg.payload = chunk
        return msg.SerializeToString()

    assert proto.parse_ble_message(make_fragment(0, 2, payload[:mid])) is None
    result = proto.parse_ble_message(make_fragment(1, 2, payload[mid:]))
    assert result == payload


def test_parse_response_device_status():
    proto = PendantProtocol()
    msg = pb.PendantAllMsg()
    msg.device_status.storage_state.total_capture_pages = 100
    msg.device_status.storage_state.free_capture_pages = 25
    msg.device_status.recording_status.recording_state = 1

    result = proto.parse_response(msg.SerializeToString())
    assert result["type"] == "device_status"
    assert result["is_recording"] is True
    assert result["storage_used_percent"] == 75


def test_extract_audio_reports_plaintext():
    proto = PendantProtocol()
    page = pb.FlashPage()
    page.absolute_timestamp_ms = 1700000000000
    chunk = page.chunks.add()
    chunk.time_offset_ms = 20
    chunk.audio_data.codec_beamforming_data = b"\xb8" * 40

    result = proto.extract_audio_from_flash_page(page.SerializeToString())
    assert result.has_plaintext_audio
    assert not result.is_encrypted
    assert result.opus_data == b"\xb8" * 40
    assert result.chunks[0].time_offset_ms == 20


def test_extract_audio_reports_encryption():
    proto = PendantProtocol()
    page = pb.FlashPage()
    chunk = page.chunks.add()
    chunk.audio_data.encrypted_codec_beamforming_data.ciphertext = b"\x00" * 16
    chunk.audio_data.encrypted_codec_beamforming_data.nonce = b"\x00" * 12
    chunk.audio_data.encrypted_codec_beamforming_data.tag = b"\x00" * 16

    result = proto.extract_audio_from_flash_page(page.SerializeToString())
    assert result.is_encrypted
    assert not result.has_plaintext_audio
    assert result.encrypted_bytes == 16
