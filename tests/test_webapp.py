import time
import wave

from pendant import audio_export, config, transcript_export, webapp
from pendant.opus_decoder import CHANNELS, SAMPLE_RATE
from pendant.transcribe import TranscriptSegment


def _fake_decode_opus_file(input_path, output_path):
    with wave.open(str(output_path), "wb") as w:
        w.setnchannels(CHANNELS)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * SAMPLE_RATE)  # 1 second of silence


def _fake_transcribe_wav(wav_path, model_size=None):
    return [TranscriptSegment(start_sec=0.0, end_sec=1.0, text="hello")]


def _make_recording(day_dir, hhmmss):
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / f"{hhmmss}_s1r0.opus").write_bytes(b"\xb8" * 10)


def _wait_for_job(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/jobs/{job_id}").get_json()
        if data["status"] != "running":
            return data
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} did not finish in time")


def test_index_page_loads(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, "RECORDINGS_DIR", tmp_path)
    client = webapp.app.test_client()

    resp = client.get("/")

    assert resp.status_code == 200
    assert b"Limitless Pendant" in resp.data
    assert b"Sync Pendant" in resp.data


def test_export_transcript_then_download(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_export, "decode_opus_file", _fake_decode_opus_file)
    monkeypatch.setattr(transcript_export, "transcribe_wav", _fake_transcribe_wav)

    recordings_dir = tmp_path / "recordings"
    transcripts_dir = tmp_path / "transcripts"
    _make_recording(recordings_dir / "2026-09-01", "090000")
    monkeypatch.setattr(config, "RECORDINGS_DIR", recordings_dir)
    monkeypatch.setattr(config, "TRANSCRIPTS_DIR", transcripts_dir)

    client = webapp.app.test_client()
    resp = client.post("/export/transcript", data={"start_date": "2026-09-01", "end_date": "2026-09-01", "format": "md"})
    assert resp.status_code == 200
    job_id = resp.get_json()["job_id"]

    data = _wait_for_job(client, job_id)
    assert data["status"] == "done", data
    assert data["result"]["filename"] == "2026-09-01.md"

    download = client.get(f"/download/{job_id}")
    assert download.status_code == 200
    assert b"hello" in download.data


def test_export_audio_then_download(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_export, "decode_opus_file", _fake_decode_opus_file)

    recordings_dir = tmp_path / "recordings"
    output_dir = tmp_path / "audio_exports"
    _make_recording(recordings_dir / "2026-09-01", "090000")
    monkeypatch.setattr(config, "RECORDINGS_DIR", recordings_dir)
    monkeypatch.setattr(config, "AUDIO_EXPORTS_DIR", output_dir)

    client = webapp.app.test_client()
    resp = client.post("/export/audio", data={"start_date": "2026-09-01", "end_date": "2026-09-01"})
    job_id = resp.get_json()["job_id"]

    data = _wait_for_job(client, job_id)
    assert data["status"] == "done", data
    assert data["result"]["filename"] == "2026-09-01_to_2026-09-01.wav"

    download = client.get(f"/download/{job_id}")
    assert download.status_code == 200


def test_sync_route_fails_cleanly_without_saved_address(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "PENDANT_ADDRESS_FILE", tmp_path / "pendant_address.txt")
    monkeypatch.delenv("PENDANT_ADDRESS", raising=False)

    client = webapp.app.test_client()
    resp = client.post("/sync")
    job_id = resp.get_json()["job_id"]

    data = _wait_for_job(client, job_id)
    assert data["status"] == "error"
    assert "scan" in data["error"]


def test_unknown_job_returns_error():
    client = webapp.app.test_client()
    resp = client.get("/jobs/does-not-exist")
    assert resp.status_code == 404


def test_download_before_done_returns_404():
    client = webapp.app.test_client()
    resp = client.get("/download/does-not-exist")
    assert resp.status_code == 404
