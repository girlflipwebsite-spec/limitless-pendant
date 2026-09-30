"""Tiny in-memory background job runner for the web GUI.

Syncing and transcribing can take a while (BLE downloads, first-time model
download, real speech-to-text). Running them directly inside a web request
would leave the browser hanging with no feedback for minutes. Instead, a
job runs in a background thread immediately, and the page polls for its
status/result - no task queue or database needed for a single local user.
"""

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

    def log_line(self, line: str) -> None:
        self.log.append(line)


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def start_job(fn: Callable[[Job], dict]) -> str:
    """Run fn(job) in a background thread and return a job id to poll.

    fn should return a result dict on success, or raise on failure - both
    are recorded on the Job for the /jobs/<id> route to report back."""
    job = Job(id=str(uuid.uuid4()))
    with _lock:
        _jobs[job.id] = job

    def run() -> None:
        try:
            job.result = fn(job)
            job.status = "done"
        except Exception as exc:
            job.error = str(exc)
            job.log_line(traceback.format_exc())
            job.status = "error"

    threading.Thread(target=run, daemon=True).start()
    return job.id


def get_job(job_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(job_id)
