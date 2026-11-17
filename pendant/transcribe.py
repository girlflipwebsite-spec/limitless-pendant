"""Local speech-to-text for downloaded recordings, using faster-whisper.

Runs entirely on-device (CPU is fine for personal-scale usage) so the whole
pipeline - pendant to transcript - stays independent of any cloud service,
matching the project's goal. ChatGPT is still the intended place for
summarization/analysis; this module only produces the plain transcript text.
"""

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_MODEL_SIZE = "base"  # good accuracy/speed tradeoff for CPU; "small"/"medium" for better accuracy

# Spoken language. Defaults to English; set PENDANT_LANGUAGE to another
# Whisper language code (e.g. "es", "fr") or to "auto" to let Whisper detect
# it per recording. Read at call time so a change takes effect without a
# code edit.
DEFAULT_LANGUAGE = "en"
AUTO_LANGUAGE_VALUES = {"auto", "detect", ""}


def get_language() -> Optional[str]:
    """Configured language code, or None meaning 'auto-detect'."""
    value = os.environ.get("PENDANT_LANGUAGE", DEFAULT_LANGUAGE).strip().lower()
    return None if value in AUTO_LANGUAGE_VALUES else value


def language_label() -> str:
    """Stable string form of get_language(), used in transcript cache keys."""
    return get_language() or "auto"


@dataclass
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str


_model_cache: dict[str, object] = {}
_model_lock = threading.Lock()


def _get_model(model_size: str = DEFAULT_MODEL_SIZE):
    # Locked so two threads asking for the same model at once can't both
    # start loading it (a second multi-hundred-MB load, or a half-built model).
    with _model_lock:
        if model_size not in _model_cache:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise ImportError(
                    "faster-whisper is required for transcription. Install it with "
                    "`pip install faster-whisper` (see README.md)."
                ) from exc
            _model_cache[model_size] = WhisperModel(model_size, device="cpu", compute_type="int8")
        return _model_cache[model_size]


def transcribe_wav(
    wav_path: str,
    model_size: str = DEFAULT_MODEL_SIZE,
    language: Optional[str] = None,
) -> list[TranscriptSegment]:
    """Transcribe a WAV file to timestamped segments. `language` defaults to
    the configured language (see get_language()); None there = auto-detect."""
    model = _get_model(model_size)
    segments, _info = model.transcribe(wav_path, language=language or get_language())
    return [
        TranscriptSegment(start_sec=seg.start, end_sec=seg.end, text=seg.text.strip())
        for seg in segments
    ]


def transcribe_wav_file(wav_path: Path, model_size: str = DEFAULT_MODEL_SIZE) -> list[TranscriptSegment]:
    return transcribe_wav(str(wav_path), model_size=model_size)
