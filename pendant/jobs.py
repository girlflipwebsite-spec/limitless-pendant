"""Tiny in-memory background job runner for the web GUI.

Syncing and transcribing can take a while (BLE downloads, first-time model
download, real speech-to-text). Running them directly inside a web request
would leave the browser hanging with no feedback for minutes. Instead, a
job starts immediately in the background and the page polls for its
status/log/result - no task queue or database needed for a single local user.

Two kinds of job:
- start_job(fn): runs a Python function in a background thread. Used for BLE
  sync, which needs to share nothing but is fast to start and I/O bound.
- start_process_job(cmd): runs a command in a separate OS process and streams
  its output into the job log. Used for exports: transcription is heavy
  native code (CTranslate2/PyAV) that doesn't belong inside the web server's
  process, and running the exact CLI command means the GUI and CLI can't
  behave differently.
"""

import subprocess
import sys
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Job:
    id: str
    status: str = "running"  # running | done | error
    log: list[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    key: Optional[str] = None  # dedupe key, e.g. "export:transcript"
    params: Optional[dict] = None  # what the job was asked to do (for the UI)

    def log_line(self, line: str) -> None:
        self.log.append(line)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _register(key: Optional[str], params: Optional[dict]) -> tuple[Job, bool]:
    """Create a job, unless one with the same key is already running - in
    which case return that one. Check-and-create happens under one lock so
    two simultaneous requests can't both start a job."""
    with _lock:
        if key is not None:
            for existing in _jobs.values():
                if existing.key == key and existing.status == "running":
                    return existing, False
        job = Job(id=str(uuid.uuid4()), key=key, params=params)
        _jobs[job.id] = job
        return job, True


def start_job(
    fn: Callable[[Job], dict], key: Optional[str] = None, params: Optional[dict] = None
) -> tuple[str, bool]:
    """Run fn(job) in a background thread. Returns (job_id, started_new).

    If `key` is given and a job with that key is still running, no new job
    is started and that job's id is returned with started_new=False.
    fn should return a result dict on success, or raise on failure."""
    job, is_new = _register(key, params)
    if not is_new:
        return job.id, False

    def run() -> None:
        try:
            job.result = fn(job)
            job.status = "done"
        except Exception as exc:
            job.error = str(exc)
            job.log_line(traceback.format_exc())
            job.status = "error"

    threading.Thread(target=run, daemon=True).start()
    return job.id, True


def cli_command(*args: str) -> list[str]:
    """Command line that runs `python -m pendant.cli <args>` with this same
    interpreter (so the venv's packages are used), unbuffered so progress
    lines arrive as they're printed."""
    return [sys.executable, "-u", "-m", "pendant.cli", *args]


def start_process_job(
    cmd: list[str], key: Optional[str] = None, params: Optional[dict] = None
) -> tuple[str, bool]:
    """Run `cmd` in a separate process; stream its output into job.log.

    The command is expected to finish by printing "Wrote <path>" (as the
    CLI's transcribe/combine-audio commands do) - that path becomes the
    job's result. A non-zero exit becomes an error carrying the command's
    own last message. Same dedupe behavior as start_job."""
    job, is_new = _register(key, params)
    if not is_new:
        return job.id, False

    def run() -> None:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            written: Optional[str] = None
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                job.log_line(line)
                if line.startswith("Wrote "):
                    written = line[len("Wrote "):].strip()
            code = proc.wait()
            if code == 0 and written:
                from pathlib import Path

                job.result = {"path": written, "filename": Path(written).name}
                job.status = "done"
            else:
                last = job.log[-1] if job.log else "no output"
                job.error = last[len("Error: "):] if last.startswith("Error: ") else (
                    f"Export process exited with code {code}: {last}"
                )
                job.status = "error"
        except Exception as exc:
            job.error = str(exc)
            job.log_line(traceback.format_exc())
            job.status = "error"

    threading.Thread(target=run, daemon=True).start()
    return job.id, True


def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)
