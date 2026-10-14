"""Acoustic simulation of a room with a speaker and a microphone.

Used by tests and by the simulated-device plugin to reproduce realistic echo
conditions without hardware: network delay, room reverberation, attenuation,
noise, and the hardware "mic ducking" behaviour observed on Tapo cameras (the
camera mutes its microphone while its own speaker plays, except for a short leak
at the start).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from justai_sdk.audio import Int16Array

SR = 16000


class _DelayLine:
    """Emitted audio indexed by time (minimal copy of the core reference buffer)."""

    def __init__(self, keep_s: float = 30.0) -> None:
        self.keep_s = keep_s
        self._chunks: list[tuple[float, Int16Array]] = []

    def add(self, t: float, pcm: Int16Array) -> None:
        self._chunks.append((t, pcm.astype(np.int16, copy=False)))
        cutoff = t - self.keep_s
        self._chunks = [c for c in self._chunks if c[0] + c[1].size / SR >= cutoff]

    def get(self, t_start: float, n: int) -> Int16Array:
        out = np.zeros(n, dtype=np.int16)
        t_end = t_start + n / SR
        for cs, chunk in self._chunks:
            ce = cs + chunk.size / SR
            if ce <= t_start or cs >= t_end:
                continue
            src0 = max(0, int(round((t_start - cs) * SR)))
            dst0 = max(0, int(round((cs - t_start) * SR)))
            length = min(chunk.size - src0, n - dst0)
            if length > 0:
                out[dst0 : dst0 + length] = chunk[src0 : src0 + length]
        return out


@dataclass
class AcousticParams:
    echo_delay_s: float = 0.8  # emission -> audible -> microphone
    echo_gain: float = 0.4
    reverb: list[tuple[float, float]] = field(
        default_factory=lambda: [(0.0, 1.0), (0.006, 0.35), (0.017, 0.15), (0.041, 0.06)])
    noise_dbfs: float = -62.0
    hardware_ducking: bool = False  # mic muted while the device speaker is active
    ducking_leak_s: float = 0.2  # leak at the start of playback before ducking engages
    seed: int = 0


class AcousticRoom:
    def __init__(self, params: AcousticParams) -> None:
        self.p = params
        self._speaker = _DelayLine(keep_s=30)
        self._user: list[tuple[float, Int16Array]] = []
        self._rng = np.random.default_rng(params.seed)
        self._ir = np.zeros(int(max(t for t, _ in params.reverb) * SR) + 1)
        for t, g in params.reverb:
            self._ir[int(t * SR)] += g
        self._voiced: list[tuple[float, float]] = []  # audible playback intervals

    def speaker_emit(self, t_emit: float, pcm: Int16Array, voiced: bool = True) -> None:
        self._speaker.add(t_emit, pcm)
        if not voiced:
            return
        frame = SR // 50  # the device's speaker activity is judged per 20 ms
        for i in range(0, pcm.size, frame):
            chunk = pcm[i : i + frame].astype(np.float64)
            if chunk.size == 0 or np.sqrt(np.mean(chunk**2)) < 100:
                continue
            start = t_emit + i / SR + self.p.echo_delay_s
            end = start + chunk.size / SR
            if self._voiced and start - self._voiced[-1][1] < 0.05:
                self._voiced[-1] = (self._voiced[-1][0], end)
            else:
                self._voiced.append((start, end))

    def user_says(self, t_start: float, pcm: Int16Array, gain: float = 1.0) -> None:
        self._user.append((t_start, (pcm.astype(np.float32) * gain).astype(np.int16)))

    def _ducked(self, t: float) -> bool:
        if not self.p.hardware_ducking:
            return False
        for start, end in self._voiced:
            if start + self.p.ducking_leak_s <= t <= end + 0.05:
                return True
        return False

    def mic(self, t: float, n: int) -> Int16Array:
        tail = self._ir.size
        far = self._speaker.get(t - self.p.echo_delay_s - tail / SR, n + tail).astype(np.float64)
        echo = np.convolve(far, self._ir)[tail : tail + n] * self.p.echo_gain
        signal = echo
        for start, pcm in self._user:
            i0 = int(round((t - start) * SR))
            if i0 + n <= 0 or i0 >= pcm.size:
                continue
            seg = np.zeros(n)
            src0, dst0 = max(0, i0), max(0, -i0)
            length = min(pcm.size - src0, n - dst0)
            seg[dst0 : dst0 + length] = pcm[src0 : src0 + length]
            signal = signal + seg
        noise = self._rng.standard_normal(n) * 32768 * 10 ** (self.p.noise_dbfs / 20)
        if self._ducked(t + n / SR / 2):
            signal = np.zeros(n)
            noise *= 0.05
        out: Int16Array = np.clip(signal + noise, -32768, 32767).astype(np.int16)
        return out
