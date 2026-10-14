"""Echo handling building blocks.

Self-speech must never be interpreted as user input (requirement 8.2). Network
cameras add large and variable echo delays (often > 1 s) that WebRTC AEC3 cannot
handle alone (it copes with ~0.5 s, see docs/AUDIO.md for the measurement). The
engine therefore combines:

* :class:`ReferenceBuffer` – what the assistant *actually emitted*, on a monotonic
  time axis shared with the microphone.
* :class:`DelayEstimator` – GCC-PHAT estimate of the end-to-end echo delay.
* :class:`EchoCanceller` – WebRTC APM (AEC3 + NS + HPF) fed with the reference
  shifted by the estimated bulk delay.
* :class:`PlaybackTracker` – knows when assistant audio can be audible, used for
  deterministic half-duplex gating and wakeword suppression.
"""

from __future__ import annotations

import bisect
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from justai_sdk.audio import Int16Array

from justai.audio.dsp import FRAME_10MS, SR


class SampleClock:
    """Assigns capture timestamps to a continuous sample stream.

    Arrival times of piped audio are bursty. The capture time of sample ``n`` is
    ``anchor + n / SR`` where the anchor tracks the earliest plausible arrival.
    """

    def __init__(self, sample_rate: int = SR, reanchor_after_s: float = 0.5) -> None:
        self.sample_rate = sample_rate
        self.reanchor_after_s = reanchor_after_s
        self._anchor: float | None = None
        self._count = 0

    def stamp(self, n_samples: int, arrival: float | None = None) -> float:
        """Return the capture time of the first of ``n_samples`` new samples."""
        now = arrival if arrival is not None else time.monotonic()
        end_offset = (self._count + n_samples) / self.sample_rate
        if self._anchor is None:
            self._anchor = now - end_offset
        else:
            candidate = now - end_offset
            if candidate < self._anchor:
                self._anchor = candidate  # data arrived earlier than expected
            elif candidate - self._anchor > self.reanchor_after_s:
                self._anchor = candidate  # stall / gap in the stream
        t = self._anchor + self._count / self.sample_rate
        self._count += n_samples
        return t

    def reset(self) -> None:
        self._anchor = None
        self._count = 0


class ReferenceBuffer:
    """Recently emitted output audio (16 kHz) indexed by emission time."""

    def __init__(self, keep_s: float = 8.0) -> None:
        self.keep_s = keep_s
        self._starts: deque[float] = deque()
        self._chunks: deque[Int16Array] = deque()

    def add(self, t_emit: float, pcm16k: Int16Array) -> None:
        if pcm16k.size == 0:
            return
        if self._starts and t_emit < self._starts[-1]:
            t_emit = self._starts[-1] + self._chunks[-1].size / SR
        self._starts.append(t_emit)
        self._chunks.append(pcm16k.astype(np.int16, copy=False))
        cutoff = t_emit - self.keep_s
        while self._starts and self._starts[0] + self._chunks[0].size / SR < cutoff:
            self._starts.popleft()
            self._chunks.popleft()

    def get(self, t_start: float, n: int) -> Int16Array:
        out = np.zeros(n, dtype=np.int16)
        if not self._starts:
            return out
        t_end = t_start + n / SR
        starts = list(self._starts) if len(self._starts) < 64 else self._starts
        i = max(0, bisect.bisect_right(starts, t_start) - 1)  # type: ignore[arg-type]
        while i < len(self._starts):
            cs = self._starts[i]
            if cs >= t_end:
                break
            chunk = self._chunks[i]
            ce = cs + chunk.size / SR
            if ce > t_start:
                src0 = max(0, int(round((t_start - cs) * SR)))
                dst0 = max(0, int(round((cs - t_start) * SR)))
                length = min(chunk.size - src0, n - dst0)
                if length > 0:
                    out[dst0 : dst0 + length] = chunk[src0 : src0 + length]
            i += 1
        return out

    def energy_db(self, t_start: float, n: int) -> float:
        ref = self.get(t_start, n).astype(np.float64)
        rms = float(np.sqrt(np.mean(ref**2))) if ref.size else 0.0
        return -120.0 if rms <= 0 else 20 * float(np.log10(rms / 32768))


@dataclass
class DelayEstimate:
    delay_s: float
    confidence: float  # peak-to-mean ratio of the GCC-PHAT correlation
    t: float


class DelayEstimator:
    """Estimates the echo delay (emission -> microphone) with GCC-PHAT."""

    def __init__(self, max_delay_s: float = 3.0, window_s: float = 1.5,
                 min_confidence: float = 12.0, history: int = 7) -> None:
        self.max_delay_s = max_delay_s
        self.window_s = window_s
        self.min_confidence = min_confidence
        self._accepted: deque[DelayEstimate] = deque(maxlen=history)
        self.last: DelayEstimate | None = None

    def estimate(self, mic: Int16Array, mic_t0: float, ref: ReferenceBuffer) -> DelayEstimate | None:
        n = mic.size
        dmax = int(self.max_delay_s * SR)
        reference = ref.get(mic_t0 - self.max_delay_s, n + dmax).astype(np.float64)
        m = mic.astype(np.float64)
        if not reference.any() or np.sqrt(np.mean(m**2)) < 30:  # mic near silence
            return None
        # The reference window starts dmax samples before the mic window. With an echo
        # delay of d samples, mic[i] ~ reference[i + dmax - d], so the correlation
        # c[k] = sum_i mic[i] * reference[i + k] peaks at k = dmax - d.
        size = 1 << int(np.ceil(np.log2(n + reference.size)))
        spec = np.fft.rfft(reference, size) * np.conj(np.fft.rfft(m, size))
        spec /= np.abs(spec) + 1e-9  # PHAT weighting
        corr = np.fft.irfft(spec, size)[: dmax + 1]
        mag = np.abs(corr)
        k = int(np.argmax(mag))
        delay_samples = dmax - k
        confidence = float(mag[k] / (np.mean(mag) + 1e-12))
        est = DelayEstimate(delay_samples / SR, confidence, mic_t0)
        self.last = est
        if confidence >= self.min_confidence:
            self._accepted.append(est)
            return est
        return None

    @property
    def delay_s(self) -> float | None:
        if not self._accepted:
            return None
        return float(np.median([e.delay_s for e in self._accepted]))

    def seed(self, delay_s: float) -> None:
        self._accepted.append(DelayEstimate(delay_s, self.min_confidence, time.monotonic()))


class EchoCanceller:
    """WebRTC APM (AEC3) on 10 ms frames with bulk delay compensation."""

    RESIDUAL_DELAY_MS = 10

    def __init__(self, *, aec: bool = True, noise_suppression: bool = True,
                 high_pass: bool = True) -> None:
        from livekit import rtc

        self._rtc = rtc
        self.aec_enabled = aec
        self._apm = rtc.AudioProcessingModule(
            echo_cancellation=aec, noise_suppression=noise_suppression,
            high_pass_filter=high_pass, auto_gain_control=False)
        if aec:
            self._apm.set_stream_delay_ms(self.RESIDUAL_DELAY_MS)

    def process(self, mic: Int16Array, reference: Int16Array | None) -> Int16Array:
        """Process one 10 ms frame (160 samples @16 kHz)."""
        if mic.size != FRAME_10MS:
            raise ValueError("APM needs 10 ms frames")
        if self.aec_enabled:
            ref = reference if reference is not None else np.zeros(FRAME_10MS, dtype=np.int16)
            rf = self._rtc.AudioFrame(ref.astype(np.int16).tobytes(), SR, 1, FRAME_10MS)
            self._apm.process_reverse_stream(rf)
        nf = self._rtc.AudioFrame(mic.astype(np.int16).tobytes(), SR, 1, FRAME_10MS)
        self._apm.process_stream(nf)
        out: Int16Array = np.frombuffer(bytes(nf.data), dtype=np.int16).copy()
        return out


class PlaybackTracker:
    """Tracks assistant speech emission to know when echo may be in the mic.

    Several bursts are remembered because the echo of an earlier burst can still be
    on its way while a new one starts.
    """

    def __init__(self, burst_gap_s: float = 1.0, keep: int = 8) -> None:
        self.burst_gap_s = burst_gap_s
        self._bursts: deque[list[float]] = deque(maxlen=keep)  # [start, last_voiced]

    @property
    def burst_start(self) -> float | None:
        return self._bursts[-1][0] if self._bursts else None

    @property
    def last_voiced(self) -> float | None:
        return self._bursts[-1][1] if self._bursts else None

    def note(self, t_emit: float, duration_s: float, voiced: bool) -> None:
        if not voiced:
            return
        if not self._bursts or t_emit - self._bursts[-1][1] > self.burst_gap_s:
            self._bursts.append([t_emit, t_emit + duration_s])
        else:
            self._bursts[-1][1] = max(self._bursts[-1][1], t_emit + duration_s)

    def in_echo_window(self, t: float, latency_s: float, tail_s: float) -> bool:
        return any(start <= t <= end + latency_s + tail_s for start, end in self._bursts)

    def echo_window_end(self, latency_s: float, tail_s: float) -> float | None:
        if not self._bursts:
            return None
        return max(end for _, end in self._bursts) + latency_s + tail_s

    def cancel(self, t: float) -> None:
        """Playback was cut (barge-in): nothing new is emitted after ``t``."""
        for burst in self._bursts:
            if burst[1] > t:
                burst[1] = max(burst[0], t)
