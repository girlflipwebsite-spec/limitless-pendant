"""Groups downloaded flash pages into recordings and saves them to disk,
organized into date folders with accurate timestamps preserved.

A "recording" here is the run of consecutive flash pages sharing the same
(session, run) identifiers from StorageBufferMsg - the natural grouping the
device itself uses for one continuous take.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import MIN_VALID_TIMESTAMP_MS, RECORDINGS_DIR
from .protocol import FlashPageAudio
from .sync_state import PageKey


@dataclass
class DownloadedPage:
    session: int
    run: int
    seq: int
    index: int
    audio: FlashPageAudio

    @property
    def key(self) -> PageKey:
        return PageKey(self.session, self.run, self.seq)


@dataclass
class Recording:
    session: int
    run: int
    opus_data: bytearray = field(default_factory=bytearray)
    encrypted_bytes: int = 0
    page_count: int = 0
    first_absolute_timestamp_ms: int = 0
    chunk_offsets: list[dict] = field(default_factory=list)

    def add_page(self, page: DownloadedPage) -> None:
        audio = page.audio
        if self.page_count == 0 and audio.absolute_timestamp_ms > MIN_VALID_TIMESTAMP_MS:
            self.first_absolute_timestamp_ms = audio.absolute_timestamp_ms

        base_offset = len(self.opus_data)
        self.opus_data.extend(audio.opus_data)
        self.encrypted_bytes += audio.encrypted_bytes
        self.page_count += 1

        for chunk in audio.chunks:
            self.chunk_offsets.append(
                {
                    "time_offset_ms": chunk.time_offset_ms,
                    "audio_offset_bytes": base_offset + chunk.audio_offset_bytes,
                    "audio_byte_length": chunk.audio_byte_length,
                    "is_encrypted": chunk.is_encrypted,
                }
            )

    @property
    def has_synced_timestamp(self) -> bool:
        return self.first_absolute_timestamp_ms > MIN_VALID_TIMESTAMP_MS

    @property
    def is_encrypted(self) -> bool:
        return self.encrypted_bytes > 0

    @property
    def has_plaintext_audio(self) -> bool:
        return len(self.opus_data) > 0


class RecordingAssembler:
    """Groups a stream of DownloadedPage objects into Recording objects."""

    def __init__(self) -> None:
        self._current: Recording | None = None
        self.completed: list[Recording] = []

    def add_page(self, page: DownloadedPage) -> None:
        if self._current is None or (
            self._current.session != page.session or self._current.run != page.run
        ):
            self._flush()
            self._current = Recording(session=page.session, run=page.run)
        self._current.add_page(page)

    def _flush(self) -> None:
        if self._current is not None and self._current.page_count > 0:
            self.completed.append(self._current)
        self._current = None

    def finish(self) -> list[Recording]:
        self._flush()
        return self.completed


def _recording_basename(recording: Recording, downloaded_at: datetime) -> tuple[str, datetime]:
    """Return (filename_stem, date_for_folder)."""
    if recording.has_synced_timestamp:
        dt = datetime.fromtimestamp(recording.first_absolute_timestamp_ms / 1000)
    else:
        dt = downloaded_at
    stem = f"{dt.strftime('%H%M%S')}_s{recording.session}r{recording.run}"
    return stem, dt


def save_recording(
    recording: Recording, base_dir: Path = RECORDINGS_DIR, downloaded_at: datetime | None = None
) -> dict:
    """Write a recording's audio + metadata sidecar into a date folder.

    Returns a dict describing what was written (paths, whether audio was
    plaintext/encrypted/empty) for the caller to report to the user.
    """
    downloaded_at = downloaded_at or datetime.now()
    stem, folder_date = _recording_basename(recording, downloaded_at)
    day_dir = base_dir / folder_date.strftime("%Y-%m-%d")
    day_dir.mkdir(parents=True, exist_ok=True)

    result = {
        "session": recording.session,
        "run": recording.run,
        "page_count": recording.page_count,
        "timestamps_synced": recording.has_synced_timestamp,
        "is_encrypted": recording.is_encrypted,
        "has_plaintext_audio": recording.has_plaintext_audio,
        "opus_path": None,
        "metadata_path": None,
    }

    if recording.has_plaintext_audio:
        opus_path = day_dir / f"{stem}.opus"
        opus_path.write_bytes(bytes(recording.opus_data))
        result["opus_path"] = str(opus_path)

    metadata = {
        "session": recording.session,
        "run": recording.run,
        "page_count": recording.page_count,
        "recording_start_ms": recording.first_absolute_timestamp_ms or None,
        "recording_start_iso": (
            datetime.fromtimestamp(recording.first_absolute_timestamp_ms / 1000).isoformat()
            if recording.has_synced_timestamp
            else None
        ),
        "downloaded_at_iso": downloaded_at.isoformat(),
        "timestamps_synced": recording.has_synced_timestamp,
        "opus_bytes": len(recording.opus_data),
        "encrypted_bytes": recording.encrypted_bytes,
        "chunks": recording.chunk_offsets,
    }
    metadata_path = day_dir / f"{stem}.json"
    metadata_path.write_text(json.dumps(metadata, indent=2))
    result["metadata_path"] = str(metadata_path)

    return result
