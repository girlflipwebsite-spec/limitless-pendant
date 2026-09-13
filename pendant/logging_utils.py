"""Session logging: every command's output is written to a timestamped file
under data/logs/ in addition to stdout, so it can be copy-pasted or attached
when reporting results back (see project plan Section 8: "prepare clear
step-by-step instructions and specific log output to request from the
client")."""

import sys
from datetime import datetime
from pathlib import Path

from .config import LOGS_DIR


class SessionLog:
    def __init__(self, command_name: str, logs_dir: Path = LOGS_DIR):
        logs_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.path = logs_dir / f"{timestamp}_{command_name}.log"
        self._fh = open(self.path, "w", encoding="utf-8")
        self.echo(f"=== pendant {command_name} - {datetime.now().isoformat()} ===")

    def echo(self, message: str = "") -> None:
        print(message)
        self._fh.write(message + "\n")
        self._fh.flush()

    def close(self) -> None:
        self.echo(f"=== end of log, saved to {self.path} ===")
        self._fh.close()

    def __enter__(self) -> "SessionLog":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            import traceback

            self.echo("")
            self.echo("EXCEPTION:")
            self.echo("".join(traceback.format_exception(exc_type, exc, tb)))
        self.close()
