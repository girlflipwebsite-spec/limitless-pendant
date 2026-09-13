"""These tests need the real libopus library installed (not just the Python
`opuslib` package) - they're skipped automatically if it's missing, which is
expected on the developer's Windows machine. They should run for real on the
client's Mac (`brew install opus`) to validate the frame-boundary-detection
heuristic against actual Opus output.
"""

import math
import struct

import pytest

try:
    import opuslib

    opuslib.Encoder(16000, 1, "audio")
except Exception:
    pytest.skip("opuslib / libopus native library not installed", allow_module_level=True)

from pendant.opus_decoder import decode_opus_bytes, parse_opus_toc


def _make_test_tone_frames(num_frames=20, frame_samples=320):
    """Encode a synthetic sine wave into `num_frames` real Opus frames,
    concatenated with no framing - exactly what the Pendant produces."""
    encoder = opuslib.Encoder(16000, 1, "audio")
    frames = []
    for i in range(num_frames):
        samples = [
            int(3000 * math.sin(2 * math.pi * 440 * (i * frame_samples + n) / 16000))
            for n in range(frame_samples)
        ]
        pcm = struct.pack(f"<{frame_samples}h", *samples)
        frames.append(encoder.encode(pcm, frame_samples))
    return b"".join(frames)


def test_parse_opus_toc_celt_20ms():
    # CELT-only fullband, 20ms, mono: config=28 -> 0b11100, stereo=0, fc=0
    toc = (28 << 3) | (0 << 2) | 0
    duration_ms, stereo = parse_opus_toc(toc)
    assert duration_ms == 20
    assert stereo is False


def test_decode_recovers_most_frames_from_synthetic_tone():
    opus_data = _make_test_tone_frames(num_frames=20, frame_samples=320)
    pcm, stats = decode_opus_bytes(opus_data)

    assert stats.frame_count >= 15  # allow some misses from the boundary heuristic
    assert len(pcm) > 0
