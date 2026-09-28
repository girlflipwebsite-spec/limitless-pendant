import wave

import pytest

from pendant import audio_export
from pendant.opus_decoder import CHANNELS, SAMPLE_RATE


def _write_silent_wav(path, seconds):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * int(SAMPLE_RATE * seconds))


def _fake_decode_opus_file(input_path, output_path):
    # Pretend every .opus decodes to a fixed 1-second clip.
    _write_silent_wav(output_path, 1.0)


def _make_recording(day_dir, hhmmss):
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{hhmmss}_s1r0.opus").write_bytes(b"\xb8" * 10)


def test_combine_audio_range_concatenates_with_gaps(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_export, "decode_opus_file", _fake_decode_opus_file)

    recordings_dir = tmp_path / "recordings"
    output_dir = tmp_path / "audio_exports"
    _make_recording(recordings_dir / "2026-09-01", "090000")
    _make_recording(recordings_dir / "2026-09-01", "093000")
    _make_recording(recordings_dir / "2026-09-03", "100000")
    # 2026-09-02 has no folder - should be skipped, not error.

    out_path = audio_export.combine_audio_range(
        "2026-09-01", "2026-09-03", recordings_dir=recordings_dir, output_dir=output_dir
    )

    assert out_path.name == "2026-09-01_to_2026-09-03.wav"
    with wave.open(str(out_path), "rb") as w:
        assert w.getframerate() == SAMPLE_RATE
        assert w.getnchannels() == CHANNELS
        duration_sec = w.getnframes() / SAMPLE_RATE
        # 3 clips of 1s each + 2 gaps of 1s each = 5s
        assert duration_sec == pytest.approx(5.0, abs=0.01)


def test_combine_audio_range_raises_when_nothing_found(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_export, "decode_opus_file", _fake_decode_opus_file)

    with pytest.raises(FileNotFoundError):
        audio_export.combine_audio_range(
            "2026-09-01", "2026-09-02", recordings_dir=tmp_path / "empty"
        )
