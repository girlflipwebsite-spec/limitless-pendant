import threading

import click
import pytest
from click.testing import CliRunner

from pendant import cli as cli_module
from pendant import transcribe, transcript_export
from pendant.ble_errors import STALE_PAIRING_MARKER, friendly_ble_error
from pendant.transcribe import TranscriptSegment


def _decode_big(input_path, output_path):
    with open(output_path, "wb") as f:
        f.write(b"\x00" * 4096)


def _decode_tiny(input_path, output_path):
    with open(output_path, "wb") as f:
        f.write(b"\x00" * 44)  # header-sized: no audio


def _make_recording(day_dir, hhmmss):
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{hhmmss}_s1r0.opus").write_bytes(b"\xb8" * 10)


@pytest.fixture
def counting_transcriber(monkeypatch):
    calls = []

    def fake(wav_path, model_size=None):
        calls.append((wav_path, model_size))
        return [TranscriptSegment(0.0, 1.0, "hello")]

    monkeypatch.setattr(transcript_export, "transcribe_wav", fake)
    monkeypatch.setattr(transcript_export, "decode_opus_file", _decode_big)
    monkeypatch.delenv("PENDANT_LANGUAGE", raising=False)
    return calls


def test_empty_recordings_are_skipped(tmp_path, monkeypatch, counting_transcriber):
    monkeypatch.setattr(transcript_export, "decode_opus_file", _decode_tiny)
    _make_recording(tmp_path / "2026-11-16", "090000")
    messages = []

    result = transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path, progress=messages.append)

    assert result == []
    assert counting_transcriber == []
    assert any("empty recording" in m for m in messages)


def test_undecodable_recording_is_skipped_not_fatal(tmp_path, monkeypatch, counting_transcriber):
    def boom(i, o):
        raise ValueError("No audio frames could be decoded")

    monkeypatch.setattr(transcript_export, "decode_opus_file", boom)
    _make_recording(tmp_path / "2026-11-16", "090000")
    assert transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path) == []


def test_transcript_cached_next_to_opus_and_reused(tmp_path, counting_transcriber):
    _make_recording(tmp_path / "2026-11-16", "090000")

    transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path)
    assert len(counting_transcriber) == 1
    assert (tmp_path / "2026-11-16" / "090000_s1r0.transcript.json").exists()

    messages = []
    again = transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path, progress=messages.append)
    assert len(counting_transcriber) == 1  # not transcribed again
    assert again[0].segments[0].text == "hello"
    assert any("saved transcript" in m for m in messages)


def test_cache_invalidated_when_model_size_changes(tmp_path, counting_transcriber):
    _make_recording(tmp_path / "2026-11-16", "090000")
    transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path, model_size="base")
    transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path, model_size="small")
    assert [c[1] for c in counting_transcriber] == ["base", "small"]


def test_cache_invalidated_when_language_changes(tmp_path, monkeypatch, counting_transcriber):
    _make_recording(tmp_path / "2026-11-16", "090000")
    transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path)
    monkeypatch.setenv("PENDANT_LANGUAGE", "es")
    transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path)
    assert len(counting_transcriber) == 2


def test_corrupt_cache_falls_back_to_transcribing(tmp_path, counting_transcriber):
    _make_recording(tmp_path / "2026-11-16", "090000")
    (tmp_path / "2026-11-16" / "090000_s1r0.transcript.json").write_text("{not json")
    transcript_export.transcribe_day("2026-11-16", recordings_dir=tmp_path)
    assert len(counting_transcriber) == 1


def test_range_progress_numbers_recordings_across_days(tmp_path, counting_transcriber):
    _make_recording(tmp_path / "2026-11-15", "090000")
    _make_recording(tmp_path / "2026-11-16", "090000")
    _make_recording(tmp_path / "2026-11-16", "100000")
    messages = []

    transcript_export.transcribe_range("2026-11-15", "2026-11-17", recordings_dir=tmp_path, progress=messages.append)

    assert [m.split(" (")[0] for m in messages] == [
        "Transcribing recording 1 of 3",
        "Transcribing recording 2 of 3",
        "Transcribing recording 3 of 3",
    ]


def test_cli_transcribe_prints_progress(tmp_path, monkeypatch, counting_transcriber):
    from pendant import config

    _make_recording(tmp_path / "recordings" / "2026-11-16", "090000")
    monkeypatch.setattr(config, "RECORDINGS_DIR", tmp_path / "recordings")
    monkeypatch.setattr(config, "TRANSCRIPTS_DIR", tmp_path / "transcripts")

    result = CliRunner().invoke(cli_module.cli, ["transcribe", "2026-11-16"])

    assert result.exit_code == 0, result.output
    assert "Transcribing recording 1 of 1" in result.output
    assert result.output.strip().splitlines()[-1].startswith("Wrote ")
    assert (tmp_path / "transcripts" / "2026-11-16.md").exists()


# ---- language setting ----

def test_language_defaults_to_english(monkeypatch):
    monkeypatch.delenv("PENDANT_LANGUAGE", raising=False)
    assert transcribe.get_language() == "en"


@pytest.mark.parametrize("value", ["auto", "AUTO", "detect", ""])
def test_language_auto_detect_is_none(monkeypatch, value):
    monkeypatch.setenv("PENDANT_LANGUAGE", value)
    assert transcribe.get_language() is None
    assert transcribe.language_label() == "auto"


def test_language_passed_to_whisper(monkeypatch):
    seen = {}

    class FakeModel:
        def transcribe(self, path, language=None):
            seen["language"] = language
            return [], None

    monkeypatch.setattr(transcribe, "_get_model", lambda size: FakeModel())
    monkeypatch.setenv("PENDANT_LANGUAGE", "fr")
    transcribe.transcribe_wav("x.wav")
    assert seen["language"] == "fr"
    monkeypatch.setenv("PENDANT_LANGUAGE", "auto")
    transcribe.transcribe_wav("x.wav")
    assert seen["language"] is None


# ---- model cache ----

def test_model_loaded_once_across_threads(monkeypatch):
    loads = []
    started = threading.Event()

    class FakeWhisperModel:
        def __init__(self, size, **kw):
            loads.append(size)
            started.wait(0.2)  # widen the race window

    import sys
    import types

    fake_mod = types.ModuleType("faster_whisper")
    fake_mod.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)
    monkeypatch.setattr(transcribe, "_model_cache", {})

    threads = [threading.Thread(target=transcribe._get_model, args=("base",)) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert loads == ["base"]


# ---- stale pairing error ----

def test_friendly_error_for_stale_pairing():
    exc = Exception('CBErrorDomain Code=14 "Peer removed pairing information"')
    text = friendly_ble_error(exc)
    assert "sudo pkill bluetoothd" in text
    assert "scan" in text


def test_friendly_error_ignores_other_errors():
    assert friendly_ble_error(Exception("something else")) is None


def test_cli_run_ble_translates_stale_pairing():
    async def fail():
        raise Exception(f"x {STALE_PAIRING_MARKER} y")

    with pytest.raises(click.ClickException) as info:
        cli_module._run_ble(fail())
    assert "sudo pkill bluetoothd" in info.value.message


def test_cli_run_ble_passes_other_errors_through():
    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        cli_module._run_ble(fail())
