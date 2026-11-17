"""Builds one clean daily transcript from a day's downloaded recordings -
ready to paste or upload into ChatGPT. This is the last step of the pipeline;
no summarization happens here, that's intentionally left to ChatGPT.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from . import config
from .opus_decoder import decode_opus_file
from .transcribe import DEFAULT_MODEL_SIZE, TranscriptSegment, language_label, transcribe_wav

# A decoded WAV smaller than this holds no usable audio (a bare header is 44
# bytes) - the Pendant sometimes saves near-empty recordings. Skip them.
MIN_WAV_BYTES = 1024

CACHE_SUFFIX = ".transcript.json"
CACHE_VERSION = 1

ProgressFn = Callable[[str], None]


@dataclass
class RecordingTranscript:
    recording_start: datetime
    segments: list[TranscriptSegment]
    source_opus: Path


def _recording_start(opus_path: Path, date_str: str) -> datetime:
    """Prefer the synced timestamp from the metadata sidecar; fall back to
    parsing the HHMMSS prefix of the filename against the folder's date."""
    meta_path = opus_path.with_suffix(".json")
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            iso = meta.get("recording_start_iso")
            if iso:
                return datetime.fromisoformat(iso)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    hhmmss = opus_path.stem.split("_", 1)[0]
    day = datetime.strptime(date_str, "%Y-%m-%d")
    return day.replace(hour=int(hhmmss[0:2]), minute=int(hhmmss[2:4]), second=int(hhmmss[4:6]))


def _cache_path(opus_path: Path) -> Path:
    return opus_path.with_name(opus_path.stem + CACHE_SUFFIX)


def _load_cached(opus_path: Path, model_size: str) -> Optional[list[TranscriptSegment]]:
    """Return cached segments if the cache matches the current model size,
    language and source file; otherwise None (so it gets re-transcribed)."""
    path = _cache_path(opus_path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (
            data.get("version") != CACHE_VERSION
            or data.get("model_size") != model_size
            or data.get("language") != language_label()
            or data.get("opus_size") != opus_path.stat().st_size
        ):
            return None
        return [
            TranscriptSegment(start_sec=s["start_sec"], end_sec=s["end_sec"], text=s["text"])
            for s in data["segments"]
        ]
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def _save_cache(opus_path: Path, model_size: str, segments: list[TranscriptSegment]) -> None:
    payload = {
        "version": CACHE_VERSION,
        "model_size": model_size,
        "language": language_label(),
        "opus_size": opus_path.stat().st_size,
        "segments": [
            {"start_sec": s.start_sec, "end_sec": s.end_sec, "text": s.text} for s in segments
        ],
    }
    target = _cache_path(opus_path)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(target)  # atomic: never leaves a half-written cache


def count_recordings(date_strs, recordings_dir: Path = None) -> int:
    recordings_dir = recordings_dir if recordings_dir is not None else config.RECORDINGS_DIR
    return sum(
        len(list((recordings_dir / d).glob("*.opus")))
        for d in date_strs
        if (recordings_dir / d).exists()
    )


def transcribe_day(
    date_str: str,
    recordings_dir: Path = None,
    model_size: str = DEFAULT_MODEL_SIZE,
    progress: Optional[ProgressFn] = None,
    _index_offset: int = 0,
    _total: Optional[int] = None,
) -> list[RecordingTranscript]:
    """Decode + transcribe every recording in recordings/<date_str>/, in
    chronological order. Near-empty recordings are skipped, and each
    recording's transcript is cached next to its .opus so re-exports are fast.

    `progress(message)` is called once per recording ("Transcribing recording
    X of N"). _index_offset/_total let transcribe_range number recordings
    across all days instead of restarting at 1 each day."""
    recordings_dir = recordings_dir if recordings_dir is not None else config.RECORDINGS_DIR
    day_dir = recordings_dir / date_str
    if not day_dir.exists():
        raise FileNotFoundError(f"No recordings folder for {date_str}: {day_dir}")

    say = progress or (lambda _msg: None)
    opus_files = sorted(day_dir.glob("*.opus"))
    total = _total if _total is not None else len(opus_files)
    results = []
    for i, opus_path in enumerate(opus_files, start=1):
        position = f"recording {_index_offset + i} of {total}"
        segments = _load_cached(opus_path, model_size)
        if segments is not None:
            say(f"Using saved transcript for {position} ({opus_path.name})")
        else:
            wav_path = opus_path.with_suffix(".wav")
            try:
                if not wav_path.exists():
                    decode_opus_file(str(opus_path), str(wav_path))
            except ValueError as exc:  # no decodable audio frames at all
                say(f"Skipping {position} ({opus_path.name}): {exc}")
                continue
            if wav_path.stat().st_size < MIN_WAV_BYTES:
                say(f"Skipping {position} ({opus_path.name}): empty recording")
                continue
            say(f"Transcribing {position} ({opus_path.name})")
            segments = transcribe_wav(str(wav_path), model_size=model_size)
            _save_cache(opus_path, model_size, segments)
        results.append(
            RecordingTranscript(
                recording_start=_recording_start(opus_path, date_str),
                segments=segments,
                source_opus=opus_path,
            )
        )
    return results


def _format_markdown(date_str: str, recordings: list[RecordingTranscript]) -> str:
    lines = [f"# Transcript for {date_str}", ""]
    for rec in recordings:
        lines.append(f"## {rec.recording_start.strftime('%H:%M:%S')}")
        lines.append("")
        for seg in rec.segments:
            ts = (rec.recording_start + timedelta(seconds=seg.start_sec)).strftime("%H:%M:%S")
            lines.append(f"**[{ts}]** {seg.text}")
        lines.append("")
    return "\n".join(lines)


def _format_txt(date_str: str, recordings: list[RecordingTranscript]) -> str:
    lines = [f"Transcript for {date_str}", ""]
    for rec in recordings:
        for seg in rec.segments:
            ts = (rec.recording_start + timedelta(seconds=seg.start_sec)).strftime("%H:%M:%S")
            lines.append(f"[{ts}] {seg.text}")
    return "\n".join(lines)


def _format_json(date_str: str, recordings: list[RecordingTranscript]) -> str:
    payload = {
        "date": date_str,
        "recordings": [
            {
                "start_iso": rec.recording_start.isoformat(),
                "source_opus": str(rec.source_opus),
                "segments": [
                    {
                        "timestamp_iso": (
                            rec.recording_start + timedelta(seconds=seg.start_sec)
                        ).isoformat(),
                        "start_sec": seg.start_sec,
                        "end_sec": seg.end_sec,
                        "text": seg.text,
                    }
                    for seg in rec.segments
                ],
            }
            for rec in recordings
        ],
    }
    return json.dumps(payload, indent=2)


_FORMATTERS = {"md": _format_markdown, "txt": _format_txt, "json": _format_json}
_EXTENSIONS = {"md": ".md", "txt": ".txt", "json": ".json"}


def export_daily_transcript(
    date_str: str,
    recordings_dir: Path = None,
    transcripts_dir: Path = None,
    model_size: str = DEFAULT_MODEL_SIZE,
    output_format: str = "md",
    progress: Optional[ProgressFn] = None,
) -> Path:
    """Transcribe the whole day and write one export file. Returns its path."""
    recordings_dir = recordings_dir if recordings_dir is not None else config.RECORDINGS_DIR
    transcripts_dir = transcripts_dir if transcripts_dir is not None else config.TRANSCRIPTS_DIR
    if output_format not in _FORMATTERS:
        raise ValueError(f"Unknown output_format {output_format!r}, expected one of {list(_FORMATTERS)}")

    recordings = transcribe_day(
        date_str, recordings_dir=recordings_dir, model_size=model_size, progress=progress
    )
    content = _FORMATTERS[output_format](date_str, recordings)

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{date_str}{_EXTENSIONS[output_format]}"
    out_path.write_text(content, encoding="utf-8")
    return out_path


def _iter_dates(start_date: str, end_date: str):
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    if end < start:
        raise ValueError(f"End date {end_date} is before start date {start_date}")
    current = start
    while current <= end:
        yield current.strftime("%Y-%m-%d")
        current += timedelta(days=1)


def transcribe_range(
    start_date: str,
    end_date: str,
    recordings_dir: Path = None,
    model_size: str = DEFAULT_MODEL_SIZE,
    progress: Optional[ProgressFn] = None,
) -> dict[str, list[RecordingTranscript]]:
    """Decode + transcribe every recording across a date range (inclusive).
    Days with no recordings folder at all are skipped rather than erroring -
    a week/month export shouldn't fail just because one day is empty."""
    recordings_dir = recordings_dir if recordings_dir is not None else config.RECORDINGS_DIR
    date_list = list(_iter_dates(start_date, end_date))
    total = count_recordings(date_list, recordings_dir)
    days: dict[str, list[RecordingTranscript]] = {}
    done = 0
    for date_str in date_list:
        day_dir = recordings_dir / date_str
        if not day_dir.exists():
            continue
        days[date_str] = transcribe_day(
            date_str, recordings_dir=recordings_dir, model_size=model_size,
            progress=progress, _index_offset=done, _total=total,
        )
        done += len(list(day_dir.glob("*.opus")))
    return days


def _format_markdown_range(days: dict[str, list[RecordingTranscript]]) -> str:
    dates = sorted(days)
    lines = [f"# Transcript for {dates[0]} to {dates[-1]}", ""]
    for date_str in dates:
        recordings = days[date_str]
        if not recordings:
            continue
        lines.append(f"## {date_str}")
        lines.append("")
        for rec in recordings:
            lines.append(f"### {rec.recording_start.strftime('%H:%M:%S')}")
            lines.append("")
            for seg in rec.segments:
                ts = (rec.recording_start + timedelta(seconds=seg.start_sec)).strftime("%H:%M:%S")
                lines.append(f"**[{ts}]** {seg.text}")
            lines.append("")
    return "\n".join(lines)


def _format_txt_range(days: dict[str, list[RecordingTranscript]]) -> str:
    lines = []
    for date_str in sorted(days):
        recordings = days[date_str]
        if not recordings:
            continue
        lines.append(f"=== {date_str} ===")
        for rec in recordings:
            for seg in rec.segments:
                ts = (rec.recording_start + timedelta(seconds=seg.start_sec)).strftime("%H:%M:%S")
                lines.append(f"[{ts}] {seg.text}")
        lines.append("")
    return "\n".join(lines)


def _format_json_range(days: dict[str, list[RecordingTranscript]]) -> str:
    payload = {
        "start_date": min(days) if days else None,
        "end_date": max(days) if days else None,
        "days": [
            {
                "date": date_str,
                "recordings": [
                    {
                        "start_iso": rec.recording_start.isoformat(),
                        "source_opus": str(rec.source_opus),
                        "segments": [
                            {
                                "timestamp_iso": (
                                    rec.recording_start + timedelta(seconds=seg.start_sec)
                                ).isoformat(),
                                "start_sec": seg.start_sec,
                                "end_sec": seg.end_sec,
                                "text": seg.text,
                            }
                            for seg in rec.segments
                        ],
                    }
                    for rec in recordings
                ],
            }
            for date_str, recordings in sorted(days.items())
            if recordings
        ],
    }
    return json.dumps(payload, indent=2)


_RANGE_FORMATTERS = {"md": _format_markdown_range, "txt": _format_txt_range, "json": _format_json_range}


def export_transcript_range(
    start_date: str,
    end_date: str,
    recordings_dir: Path = None,
    transcripts_dir: Path = None,
    model_size: str = DEFAULT_MODEL_SIZE,
    output_format: str = "md",
    progress: Optional[ProgressFn] = None,
) -> Path:
    """Transcribe a date range (inclusive) - e.g. a week or a month - and
    write one combined export file. Returns its path."""
    recordings_dir = recordings_dir if recordings_dir is not None else config.RECORDINGS_DIR
    transcripts_dir = transcripts_dir if transcripts_dir is not None else config.TRANSCRIPTS_DIR
    if output_format not in _RANGE_FORMATTERS:
        raise ValueError(f"Unknown output_format {output_format!r}, expected one of {list(_RANGE_FORMATTERS)}")

    days = transcribe_range(
        start_date, end_date, recordings_dir=recordings_dir, model_size=model_size, progress=progress
    )
    if not any(days.values()):
        raise FileNotFoundError(f"No recordings found between {start_date} and {end_date}")

    content = _RANGE_FORMATTERS[output_format](days)

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{start_date}_to_{end_date}{_EXTENSIONS[output_format]}"
    out_path.write_text(content, encoding="utf-8")
    return out_path
