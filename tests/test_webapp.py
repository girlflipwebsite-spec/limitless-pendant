import sys
import threading
import time
import wave
from pathlib import Path

import pytest
from click.testing import CliRunner

from pendant import audio_export, config, jobs, transcript_export, webapp
from pendant.cli import cli
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


@pytest.fixture(autouse=True)
def in_process_cli_jobs(monkeypatch):
    """The real app runs exports as a separate process. Tests can't patch a
    child process, so run the same CLI command in-process (via click's
    runner) in a background job instead - this still exercises the real
    command-line arguments the web routes build."""
    def fake_start(key, params, *cli_args):
        def task(job):
            result = CliRunner().invoke(cli, list(cli_args))
            for line in result.output.splitlines():
                job.log_line(line)
            if result.exit_code != 0:
                raise RuntimeError(result.output.strip().splitlines()[-1] if result.output else str(result.exception))
            written = [l for l in result.output.splitlines() if l.startswith("Wrote ")][-1][6:]
            return {"path": written, "filename": Path(written).name}
        return jobs.start_job(task, key=key, params=params)

    monkeypatch.setattr(webapp, "_start_cli_job", fake_start)


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


def test_job_log_exposed_with_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(transcript_export, "decode_opus_file", _fake_decode_opus_file)
    monkeypatch.setattr(transcript_export, "transcribe_wav", _fake_transcribe_wav)
    recordings_dir = tmp_path / "recordings"
    _make_recording(recordings_dir / "2026-09-01", "090000")
    _make_recording(recordings_dir / "2026-09-01", "100000")
    monkeypatch.setattr(config, "RECORDINGS_DIR", recordings_dir)
    monkeypatch.setattr(config, "TRANSCRIPTS_DIR", tmp_path / "transcripts")

    client = webapp.app.test_client()
    job_id = client.post("/export/transcript", data={"start_date": "2026-09-01"}).get_json()["job_id"]
    data = _wait_for_job(client, job_id)

    assert data["status"] == "done", data
    log = "\n".join(data["log"])
    assert "Transcribing recording 1 of 2" in log
    assert "Transcribing recording 2 of 2" in log


def test_duplicate_export_returns_running_job(monkeypatch):
    release = threading.Event()

    def slow_start(key, params, *cli_args):
        return jobs.start_job(lambda job: (release.wait(5), {"path": "x", "filename": "x"})[1], key=key, params=params)

    monkeypatch.setattr(webapp, "_start_cli_job", slow_start)
    client = webapp.app.test_client()
    try:
        first = client.post("/export/transcript", data={"start_date": "2026-09-01"}).get_json()
        second = client.post("/export/transcript", data={"start_date": "2026-09-05", "end_date": "2026-09-09"}).get_json()
        assert first["already_running"] is False
        assert second["already_running"] is True
        assert second["job_id"] == first["job_id"]
        assert second["params"]["start_date"] == "2026-09-01"  # tells the page what is really running
    finally:
        release.set()
    _wait_for_job(client, first["job_id"])
    # once finished, a new export starts normally
    third = client.post("/export/transcript", data={"start_date": "2026-09-01"}).get_json()
    assert third["already_running"] is False
    assert third["job_id"] != first["job_id"]
    release.set()


def test_export_requires_start_date():
    client = webapp.app.test_client()
    assert client.post("/export/transcript", data={}).status_code == 400
    assert client.post("/export/audio", data={}).status_code == 400


def test_page_javascript_is_syntactically_valid(tmp_path):
    """The page's script lives inside a Python string, where an unescaped
    backslash-n becomes a real newline inside a JS string literal - a syntax
    error that silently kills every button. Parse the served script for real."""
    import re
    import shutil
    import subprocess

    page = webapp.app.test_client().get("/").get_data(as_text=True)
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)

    node = shutil.which("node")
    if node is None:
        # No node available: at least catch the specific mistake.
        for line in script.splitlines():
            assert line.count("'") % 2 == 0, f"unterminated JS string: {line!r}"
        return
    js = tmp_path / "page.js"
    js.write_text(script, encoding="utf-8")
    result = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_page_handles_lost_connection():
    page = webapp.app.test_client().get("/").get_data(as_text=True)
    assert "Lost connection to the local server" in page
    assert page.count(".catch(") >= 3  # poll + sync fetch + export fetch


def test_process_job_runs_real_subprocess_and_captures_progress_and_result():
    code = "print('Transcribing recording 1 of 1', flush=True); print('Wrote /tmp/out.md')"
    job_id, started = jobs.start_process_job([sys.executable, "-c", code], key="t-proc")
    assert started
    deadline = time.time() + 10
    while jobs.get_job(job_id).status == "running" and time.time() < deadline:
        time.sleep(0.05)
    job = jobs.get_job(job_id)
    assert job.status == "done", job.error
    assert job.result["filename"] == "out.md"
    assert "Transcribing recording 1 of 1" in job.log


def test_process_job_reports_failure():
    job_id, _ = jobs.start_process_job(
        [sys.executable, "-c", "import sys; print('Error: nothing to do'); sys.exit(1)"], key="t-fail"
    )
    deadline = time.time() + 10
    while jobs.get_job(job_id).status == "running" and time.time() < deadline:
        time.sleep(0.05)
    job = jobs.get_job(job_id)
    assert job.status == "error"
    assert job.error == "nothing to do"
