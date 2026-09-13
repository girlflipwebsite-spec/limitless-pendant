"""Builds one clean daily transcript from a day's downloaded recordings -
ready to paste or upload into ChatGPT. This is the last step of the pipeline;
no summarization happens here, that's intentionally left to ChatGPT.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .config import RECORDINGS_DIR, TRANSCRIPTS_DIR
from .opus_decoder import decode_opus_file
from .transcribe import DEFAULT_MODEL_SIZE, TranscriptSegment, transcribe_wav


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


def transcribe_day(
    date_str: str,
    recordings_dir: Path = RECORDINGS_DIR,
    model_size: str = DEFAULT_MODEL_SIZE,
) -> list[RecordingTranscript]:
    """Decode + transcribe every recording in recordings/<date_str>/, in
    chronological order."""
    day_dir = recordings_dir / date_str
    if not day_dir.exists():
        raise FileNotFoundError(f"No recordings folder for {date_str}: {day_dir}")

    opus_files = sorted(day_dir.glob("*.opus"))
    results = []
    for opus_path in opus_files:
        wav_path = opus_path.with_suffix(".wav")
        if not wav_path.exists():
            decode_opus_file(str(opus_path), str(wav_path))
        segments = transcribe_wav(str(wav_path), model_size=model_size)
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
    recordings_dir: Path = RECORDINGS_DIR,
    transcripts_dir: Path = TRANSCRIPTS_DIR,
    model_size: str = DEFAULT_MODEL_SIZE,
    output_format: str = "md",
) -> Path:
    """Transcribe the whole day and write one export file. Returns its path."""
    if output_format not in _FORMATTERS:
        raise ValueError(f"Unknown output_format {output_format!r}, expected one of {list(_FORMATTERS)}")

    recordings = transcribe_day(date_str, recordings_dir=recordings_dir, model_size=model_size)
    content = _FORMATTERS[output_format](date_str, recordings)

    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{date_str}{_EXTENSIONS[output_format]}"
    out_path.write_text(content, encoding="utf-8")
    return out_path
