"""Decode the Pendant's raw, concatenated Opus frames into PCM/WAV.

The Pendant emits Opus frames back-to-back with no Ogg container and no
frame-length headers, so frame boundaries have to be guessed from the Opus
TOC (table-of-contents) byte at the start of each frame plus a search for the
next byte matching the dominant TOC value. This mirrors the approach in
pendant-cli's decoder, which was validated against real recordings.
"""

import wave
from dataclasses import dataclass, field

SAMPLE_RATE = 16000
CHANNELS = 1
MAX_FRAME_SAMPLES = 960  # 60ms at 16kHz, the largest frame size we expect

# Opus frame duration (ms) at 16kHz -> sample count, per RFC 6716 Section 3.1.
_DURATION_TO_SAMPLES = {2.5: 40, 5: 80, 10: 160, 20: 320, 40: 640, 60: 960}

# The Pendant's encoder consistently emits this TOC byte (CELT-only, 20ms) for
# the vast majority of frames; used as a boundary hint when scanning ahead.
DOMINANT_TOC = 0xB8

_MIN_FRAME_SIZE = 30
_MAX_FRAME_SIZE = 80
_TOC_SEARCH_WINDOW = 100
_MAX_CONSECUTIVE_ERRORS = 100_000


def parse_opus_toc(toc_byte: int) -> tuple[float, bool]:
    """Return (frame_duration_ms, is_stereo) encoded in an Opus TOC byte."""
    config = (toc_byte >> 3) & 0x1F
    stereo = bool((toc_byte >> 2) & 0x01)

    if config <= 11:  # SILK-only (NB/MB/WB), 4 configs per band
        duration_ms = [10, 20, 40, 60][config % 4]
    elif config <= 15:  # Hybrid (SWB/FB), 2 configs per band
        duration_ms = [10, 20][config % 2]
    else:  # CELT-only (NB/WB/SWB/FB), 4 configs per band
        duration_ms = [2.5, 5, 10, 20][config % 4]

    return duration_ms, stereo


@dataclass
class DecodeStats:
    frame_count: int = 0
    error_bytes_skipped: int = 0
    total_duration_ms: float = 0.0
    toc_histogram: dict = field(default_factory=dict)

    @property
    def duration_sec(self) -> float:
        return self.total_duration_ms / 1000


def _find_frame(decoder, opus_data: bytes, offset: int) -> tuple[bytes, int, int, float] | None:
    """Try candidate frame sizes at `offset`; return (pcm, size, toc, duration_ms) or None."""
    remaining = len(opus_data) - offset
    toc_byte = opus_data[offset]
    duration_ms, _stereo = parse_opus_toc(toc_byte)
    expected_samples = _DURATION_TO_SAMPLES.get(duration_ms, 320)

    next_toc_distance = None
    for i in range(_MIN_FRAME_SIZE, min(_TOC_SEARCH_WINDOW, remaining)):
        if opus_data[offset + i] == DOMINANT_TOC:
            next_toc_distance = i
            break

    sizes_to_try = list(range(_MIN_FRAME_SIZE, min(_MAX_FRAME_SIZE, remaining) + 1))
    if next_toc_distance is not None and next_toc_distance in sizes_to_try:
        sizes_to_try.remove(next_toc_distance)
        sizes_to_try.insert(0, next_toc_distance)

    for size in sizes_to_try:
        frame = opus_data[offset : offset + size]
        if not frame:
            continue
        try:
            pcm = decoder.decode(frame, max(expected_samples, MAX_FRAME_SAMPLES))
        except Exception:
            continue
        if not pcm:
            continue
        actual_samples = len(pcm) // 2
        if actual_samples == expected_samples or size == next_toc_distance:
            return pcm, size, toc_byte, duration_ms
    return None


def decode_opus_bytes(opus_data: bytes) -> tuple[bytes, DecodeStats]:
    """Decode raw concatenated Opus frames to 16-bit PCM. Returns (pcm, stats)."""
    try:
        import opuslib
    except ImportError as exc:
        raise ImportError(
            "opuslib is required for audio decoding. Install it with `pip install opuslib` "
            "(requires the libopus system library - see README.md)."
        ) from exc

    decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)
    stats = DecodeStats()
    pcm_chunks: list[bytes] = []
    offset = 0

    while offset < len(opus_data):
        found = _find_frame(decoder, opus_data, offset)
        if found is None:
            offset += 1
            stats.error_bytes_skipped += 1
            if stats.error_bytes_skipped > _MAX_CONSECUTIVE_ERRORS:
                break
            continue

        pcm, size, toc, duration_ms = found
        pcm_chunks.append(pcm)
        offset += size
        stats.frame_count += 1
        stats.total_duration_ms += duration_ms
        stats.toc_histogram[toc] = stats.toc_histogram.get(toc, 0) + 1

    return b"".join(pcm_chunks), stats


def write_wav(pcm_data: bytes, output_path: str) -> None:
    with wave.open(output_path, "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm_data)


def decode_opus_file(input_path: str, output_path: str) -> DecodeStats:
    """Decode a raw .opus file (as saved by pendant.audio_store) to a .wav file."""
    with open(input_path, "rb") as f:
        opus_data = f.read()
    pcm, stats = decode_opus_bytes(opus_data)
    if not pcm:
        raise ValueError(f"No audio frames could be decoded from {input_path}")
    write_wav(pcm, output_path)
    return stats
