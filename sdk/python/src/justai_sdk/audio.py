"""Audio primitives. All audio inside JuStAI5 is mono signed 16-bit PCM."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

Int16Array = npt.NDArray[np.int16]


@dataclass(frozen=True, slots=True)
class AudioChunk:
    pcm: Int16Array
    sample_rate: int

    @property
    def samples(self) -> int:
        return int(self.pcm.shape[0])

    @property
    def duration_s(self) -> float:
        return self.samples / self.sample_rate

    def to_bytes(self) -> bytes:
        return self.pcm.astype("<i2", copy=False).tobytes()

    @classmethod
    def from_bytes(cls, data: bytes, sample_rate: int) -> AudioChunk:
        usable = len(data) - (len(data) % 2)
        return cls(np.frombuffer(data[:usable], dtype="<i2").astype(np.int16), sample_rate)

    @classmethod
    def silence(cls, duration_s: float, sample_rate: int) -> AudioChunk:
        return cls(np.zeros(int(duration_s * sample_rate), dtype=np.int16), sample_rate)


def rms_dbfs(pcm: Int16Array) -> float:
    """RMS level in dBFS (-inf for digital silence is clamped to -120)."""
    if pcm.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(pcm.astype(np.float64)))))
    if rms <= 0:
        return -120.0
    return max(-120.0, 20.0 * float(np.log10(rms / 32768.0)))
