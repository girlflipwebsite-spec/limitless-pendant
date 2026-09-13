import json

from pendant.audio_store import DownloadedPage, RecordingAssembler, save_recording
from pendant.protocol import ChunkInfo, FlashPageAudio


def _page(session, run, seq, index, ts_ms, opus_bytes=b"\xb8" * 20, encrypted=0):
    audio = FlashPageAudio(
        absolute_timestamp_ms=ts_ms,
        boot_uptime_ms=0,
        opus_data=opus_bytes,
        encrypted_bytes=encrypted,
        chunks=[ChunkInfo(0, 0, len(opus_bytes), encrypted > 0)],
    )
    return DownloadedPage(session=session, run=run, seq=seq, index=index, audio=audio)


def test_assembler_groups_by_session_and_run():
    assembler = RecordingAssembler()
    assembler.add_page(_page(1, 0, 0, 0, 1_700_000_000_000))
    assembler.add_page(_page(1, 0, 1, 1, 1_700_000_001_000))
    assembler.add_page(_page(2, 0, 0, 2, 1_700_000_002_000))

    recordings = assembler.finish()
    assert len(recordings) == 2
    assert recordings[0].page_count == 2
    assert recordings[1].page_count == 1
    assert len(recordings[0].opus_data) == 40


def test_save_recording_writes_opus_and_metadata(tmp_path):
    assembler = RecordingAssembler()
    assembler.add_page(_page(1, 0, 0, 0, 1_700_000_000_000, opus_bytes=b"\xb8" * 10))
    recording = assembler.finish()[0]

    saved = save_recording(recording, base_dir=tmp_path)

    assert saved["has_plaintext_audio"] is True
    assert saved["is_encrypted"] is False
    assert list(tmp_path.rglob("*.opus"))
    assert list(tmp_path.rglob("*.json"))

    meta = json.loads(list(tmp_path.rglob("*.json"))[0].read_text())
    assert meta["recording_start_iso"] is not None
    assert meta["opus_bytes"] == 10


def test_save_recording_marks_encrypted_without_writing_opus(tmp_path):
    assembler = RecordingAssembler()
    assembler.add_page(_page(1, 0, 0, 0, 1_700_000_000_000, opus_bytes=b"", encrypted=32))
    recording = assembler.finish()[0]

    saved = save_recording(recording, base_dir=tmp_path)

    assert saved["is_encrypted"] is True
    assert saved["has_plaintext_audio"] is False
    assert saved["opus_path"] is None
    assert not list(tmp_path.rglob("*.opus"))
