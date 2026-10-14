"""DSP helpers: streaming resampling and fixed-size framing."""

from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import soxr
from justai_sdk.audio import Int16Array

SR = 16000  # internal processing rate
FRAME_10MS = SR // 100  # 160 samples


class StreamResampler:
    """Streaming int16 resampler (soxr, high quality, low latency)."""

    def __init__(self, in_rate: int, out_rate: int) -> None:
        self.in_rate = in_rate
        self.out_rate = out_rate
        self._passthrough = in_rate == out_rate
        self._stream = None if self._passthrough else soxr.ResampleStream(
            in_rate, out_rate, 1, dtype="int16", quality="HQ")

    def process(self, pcm: Int16Array, last: bool = False) -> Int16Array:
        if self._passthrough or self._stream is None:
            return pcm
        out: Int16Array = self._stream.resample_chunk(pcm, last=last)
        return out


def resample(pcm: Int16Array, in_rate: int, out_rate: int) -> Int16Array:
    if in_rate == out_rate:
        return pcm
    out: Int16Array = soxr.resample(pcm, in_rate, out_rate, quality="HQ").astype(np.int16)
    return out


class Framer:
    """Accumulates arbitrary-length chunks and yields fixed-size frames."""

    def __init__(self, frame_samples: int) -> None:
        self.frame_samples = frame_samples
        self._buf = np.zeros(0, dtype=np.int16)

    def push(self, pcm: Int16Array) -> Iterator[Int16Array]:
        self._buf = np.concatenate([self._buf, pcm]) if self._buf.size else pcm.copy()
        n = self.frame_samples
        whole = (self._buf.size // n) * n
        for i in range(0, whole, n):
            yield self._buf[i : i + n]
        self._buf = self._buf[whole:]

    def reset(self) -> None:
        self._buf = np.zeros(0, dtype=np.int16)


def dbfs(pcm: Int16Array) -> float:
    if pcm.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(pcm.astype(np.float64) ** 2)))
    return -120.0 if rms <= 1e-9 else max(-120.0, 20.0 * np.log10(rms / 32768.0))


def apply_gain(pcm: Int16Array, gain_db: float) -> Int16Array:
    if gain_db == 0:
        return pcm
    factor = 10 ** (gain_db / 20)
    out: Int16Array = np.clip(pcm.astype(np.float32) * factor, -32768, 32767).astype(np.int16)
    return out
