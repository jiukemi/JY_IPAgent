"""Smoke tests for dubbing segment splice helpers."""

from __future__ import annotations

import math
import struct
import tempfile
import wave
from pathlib import Path

import pytest

from tts.dubbing_patch import fit_wav_duration, splice_with_crossfade


def _write_sine(path: Path, duration: float, sr: int = 16000, freq: float = 440.0) -> None:
    n = int(duration * sr)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for i in range(n):
            val = int(12000 * math.sin(2 * math.pi * freq * (i / sr)))
            frames += struct.pack("<h", val)
        wf.writeframes(frames)


def _dur(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 1)


@pytest.fixture(scope="module")
def ffmpeg_bin():
    from pipeline import ensure_ffmpeg

    try:
        return ensure_ffmpeg("ffmpeg")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ffmpeg unavailable: {exc}")


def test_fit_and_splice_keeps_timeline(ffmpeg_bin, tmp_path: Path):
    base = tmp_path / "base.wav"
    mid = tmp_path / "mid.wav"
    fit = tmp_path / "fit.wav"
    out = tmp_path / "out.wav"
    _write_sine(base, 3.0, freq=220.0)
    _write_sine(mid, 1.4, freq=660.0)  # longer than 1.0s slot

    fit_wav_duration(ffmpeg_bin, mid, fit, 1.0)
    assert abs(_dur(fit) - 1.0) < 0.05

    splice_with_crossfade(ffmpeg_bin, base, fit, out, 1.0, 2.0, crossfade_ms=30)
    assert abs(_dur(out) - 3.0) < 0.08
