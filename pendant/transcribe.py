"""Local speech-to-text for downloaded recordings, using faster-whisper.

Runs entirely on-device (CPU is fine for personal-scale usage) so the whole
pipeline - pendant to transcript - stays independent of any cloud service,
matching the project's goal. ChatGPT is still the intended place for
summarization/analysis; this module only produces the plain transcript text.
"""

from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL_SIZE = "base"  # good accuracy/speed tradeoff for CPU; "small"/"medium" for better accuracy


@dataclass
class TranscriptSegment:
    start_sec: float
    end_sec: float
    text: str


_model_cache: dict[str, object] = {}


def _get_model(model_size: str = DEFAULT_MODEL_SIZE):
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


def transcribe_wav(wav_path: str, model_size: str = DEFAULT_MODEL_SIZE) -> list[TranscriptSegment]:
    """Transcribe a WAV file to timestamped segments."""
    model = _get_model(model_size)
    segments, _info = model.transcribe(wav_path, language="en")
    return [
        TranscriptSegment(start_sec=seg.start, end_sec=seg.end, text=seg.text.strip())
        for seg in segments
    ]


def transcribe_wav_file(wav_path: Path, model_size: str = DEFAULT_MODEL_SIZE) -> list[TranscriptSegment]:
    return transcribe_wav(str(wav_path), model_size=model_size)
