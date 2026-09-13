"""Tracks which flash pages have already been downloaded, so re-running sync
doesn't re-save recordings we already have.

The Pendant's DownloadFlashPages command streams every page currently held in
its flash storage - there's no "give me only what's new" request in the
protocol (see PROTOCOL.md). So "don't re-download" has to happen on our side:
we remember each page's (session, run, seq) key and skip pages we've already
saved to disk.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from .config import SYNC_STATE_PATH


@dataclass(frozen=True)
class PageKey:
    session: int
    run: int
    seq: int

    def as_str(self) -> str:
        return f"{self.session}:{self.run}:{self.seq}"


class SyncState:
    """Persisted set of already-downloaded page keys plus last-sync bookkeeping."""

    def __init__(self, path: Path = SYNC_STATE_PATH):
        self.path = path
        self._seen_pages: set[str] = set()
        self.last_sync_iso: str | None = None
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        self._seen_pages = set(data.get("seen_pages", []))
        self.last_sync_iso = data.get("last_sync_iso")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "seen_pages": sorted(self._seen_pages),
                    "last_sync_iso": self.last_sync_iso,
                },
                indent=2,
            )
        )

    def is_new(self, key: PageKey) -> bool:
        return key.as_str() not in self._seen_pages

    def mark_seen(self, key: PageKey) -> None:
        self._seen_pages.add(key.as_str())

    def __len__(self) -> int:
        return len(self._seen_pages)
