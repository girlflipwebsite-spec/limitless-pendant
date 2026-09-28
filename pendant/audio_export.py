"""Combines a day's (or a date range's) recordings into one continuous,
playable WAV file - for listening back to a stretch of time directly,
rather than only reading a transcript.

This does not attempt to reconstruct real elapsed time between recordings
(the gaps between clips can be minutes or hours) - it just concatenates the
actual recorded audio in chronological order with a short fixed silence
between clips, so the result is compact and continuously listenable rather
than mostly silence.
"""

import wave
from pathlib import Path

from .config import AUDIO_EXPORTS_DIR, RECORDINGS_DIR
from .opus_decoder import CHANNELS, SAMPLE_RATE, decode_opus_file
from .transcript_export import _iter_dates

GAP_SECONDS = 1.0
_SILENCE_FRAME = b"\x00\x00"  # one 16-bit silent sample


def _silence(seconds: float) -> bytes:
    return _SILENCE_FRAME * int(SAMPLE_RATE * seconds)


def combine_audio_range(
    start_date: str,
    end_date: str,
    recordings_dir: Path = RECORDINGS_DIR,
    output_dir: Path = AUDIO_EXPORTS_DIR,
) -> Path:
    """Decode and concatenate every recording between start_date and
    end_date (inclusive) into one WAV file, in chronological order. Days
    with no recordings folder are skipped, not an error. Returns the
    output path."""
    opus_files: list[Path] = []
    for date_str in _iter_dates(start_date, end_date):
        day_dir = recordings_dir / date_str
        if day_dir.exists():
            opus_files.extend(sorted(day_dir.glob("*.opus")))

    if not opus_files:
        raise FileNotFoundError(f"No recordings found between {start_date} and {end_date}")

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{start_date}_to_{end_date}.wav"

    with wave.open(str(out_path), "wb") as out_wav:
        out_wav.setnchannels(CHANNELS)
        out_wav.setsampwidth(2)  # 16-bit
        out_wav.setframerate(SAMPLE_RATE)

        for i, opus_path in enumerate(opus_files):
            wav_path = opus_path.with_suffix(".wav")
            if not wav_path.exists():
                decode_opus_file(str(opus_path), str(wav_path))
            with wave.open(str(wav_path), "rb") as in_wav:
                out_wav.writeframes(in_wav.readframes(in_wav.getnframes()))
            if i < len(opus_files) - 1:
                out_wav.writeframes(_silence(GAP_SECONDS))

    return out_path
