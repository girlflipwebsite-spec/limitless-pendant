from pendant import transcript_export
from pendant.transcribe import TranscriptSegment


def _fake_decode_opus_file(input_path, output_path):
    # transcribe_day only checks that the .wav file exists afterward.
    with open(output_path, "wb") as f:
        f.write(b"")


def _fake_transcribe_wav(wav_path, model_size=None):
    return [TranscriptSegment(start_sec=0.0, end_sec=1.0, text=f"hello from {wav_path}")]


def _make_recording(day_dir, hhmmss):
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{hhmmss}_s1r0.opus").write_bytes(b"\xb8" * 10)


def test_transcribe_range_skips_missing_days(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_export, "decode_opus_file", _fake_decode_opus_file)
    monkeypatch.setattr(transcript_export, "transcribe_wav", _fake_transcribe_wav)

    _make_recording(tmp_path / "2026-09-01", "090000")
    _make_recording(tmp_path / "2026-09-03", "100000")
    # 2026-09-02 has no folder at all - should be skipped, not error.

    days = transcript_export.transcribe_range("2026-09-01", "2026-09-03", recordings_dir=tmp_path)

    assert set(days) == {"2026-09-01", "2026-09-03"}
    assert len(days["2026-09-01"]) == 1
    assert len(days["2026-09-03"]) == 1


def test_export_transcript_range_writes_combined_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_export, "decode_opus_file", _fake_decode_opus_file)
    monkeypatch.setattr(transcript_export, "transcribe_wav", _fake_transcribe_wav)

    recordings_dir = tmp_path / "recordings"
    transcripts_dir = tmp_path / "transcripts"
    _make_recording(recordings_dir / "2026-09-01", "090000")
    _make_recording(recordings_dir / "2026-09-02", "153000")

    out_path = transcript_export.export_transcript_range(
        "2026-09-01", "2026-09-02", recordings_dir=recordings_dir, transcripts_dir=transcripts_dir
    )

    assert out_path.name == "2026-09-01_to_2026-09-02.md"
    content = out_path.read_text()
    assert "2026-09-01" in content
    assert "2026-09-02" in content
    assert "09:00:00" in content
    assert "15:30:00" in content


def test_export_transcript_range_raises_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_export, "decode_opus_file", _fake_decode_opus_file)
    monkeypatch.setattr(transcript_export, "transcribe_wav", _fake_transcribe_wav)

    import pytest

    with pytest.raises(FileNotFoundError):
        transcript_export.export_transcript_range(
            "2026-09-01", "2026-09-02", recordings_dir=tmp_path / "empty"
        )
