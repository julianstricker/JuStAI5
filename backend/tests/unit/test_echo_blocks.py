import numpy as np
import pytest

from justai.audio.dsp import SR
from justai.audio.echo import (
    DelayEstimator,
    EchoCanceller,
    PlaybackTracker,
    ReferenceBuffer,
    SampleClock,
)


def speechlike(seconds: float, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    env = (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t)) ** 2
    return (rng.standard_normal(t.size) * 5000 * env).astype(np.int16)


def test_reference_buffer_returns_samples_by_time() -> None:
    ref = ReferenceBuffer()
    a = np.arange(320, dtype=np.int16)
    ref.add(100.0, a)
    out = ref.get(100.0 + 160 / SR, 320)
    assert np.array_equal(out[:160], a[160:])
    assert not out[160:].any()
    assert not ref.get(50.0, 100).any()


@pytest.mark.parametrize("delay_s", [0.12, 0.8, 1.9])
def test_delay_estimator_finds_large_network_delays(delay_s: float) -> None:
    ref = ReferenceBuffer(keep_s=10)
    far = speechlike(6.0)
    t0 = 1000.0
    for i in range(0, far.size, 320):  # emitted in 20 ms chunks
        ref.add(t0 + i / SR, far[i:i + 320])
    d = int(delay_s * SR)
    mic = np.zeros(far.size + d, dtype=np.float64)
    mic[d:] = far * 0.3
    mic += np.random.default_rng(1).standard_normal(mic.size) * 40
    mic = mic.astype(np.int16)
    est = DelayEstimator(max_delay_s=2.5)
    window = int(1.5 * SR)
    start = int(3.0 * SR)
    result = est.estimate(mic[start:start + window], t0 + start / SR, ref)
    assert result is not None
    assert abs(result.delay_s - delay_s) < 0.005


def test_delay_estimator_rejects_uncorrelated_audio() -> None:
    ref = ReferenceBuffer()
    far = speechlike(4.0, seed=1)
    ref.add(0.0, far)
    other = speechlike(1.5, seed=7)
    assert DelayEstimator().estimate(other, 2.0, ref) is None


def test_aec_with_bulk_delay_compensation() -> None:
    """End-to-end: 1.2 s network echo is cancelled when the reference is pre-aligned."""
    delay_s = 1.2
    far = speechlike(10.0, seed=3)
    ref = ReferenceBuffer(keep_s=12)
    t0 = 500.0
    ref.add(t0, far)
    d = int(delay_s * SR)
    ir = np.zeros(300)
    ir[0], ir[90], ir[220] = 0.5, 0.2, 0.08
    echo_path = np.convolve(far.astype(float), ir)[: far.size]
    mic = np.zeros(far.size)
    mic[d:] = echo_path[: far.size - d]
    mic = (mic + np.random.default_rng(2).standard_normal(mic.size) * 30).astype(np.int16)

    aec = EchoCanceller(noise_suppression=False)
    out = []
    for i in range(0, mic.size - 160, 160):
        t_mic = t0 + i / SR
        out.append(aec.process(mic[i:i + 160], ref.get(t_mic - delay_s + 0.01, 160)))
    o = np.concatenate(out).astype(float)
    tail = slice(int(6 * SR), o.size)
    erle = 10 * np.log10(np.mean(mic[tail].astype(float) ** 2) / np.mean(o[tail] ** 2))
    assert erle > 20, f"ERLE {erle:.1f} dB"


def test_playback_tracker_echo_window() -> None:
    p = PlaybackTracker()
    p.note(10.0, 0.02, voiced=True)
    p.note(12.0, 0.02, voiced=True)  # gap > 1 s -> a new burst starts
    assert p.burst_start == 12.0
    p.note(12.5, 0.5, voiced=True)  # same burst, voiced until 13.0
    # The echo of the first burst (10.0-10.02) can still arrive until 12.02.
    assert p.in_echo_window(11.9, latency_s=1.5, tail_s=0.5)
    assert not p.in_echo_window(9.9, latency_s=1.5, tail_s=0.5)
    assert p.in_echo_window(12.1, latency_s=1.5, tail_s=0.5)
    assert p.in_echo_window(14.9, latency_s=1.5, tail_s=0.5)
    assert not p.in_echo_window(15.1, latency_s=1.5, tail_s=0.5)
    p.cancel(12.6)  # barge-in: nothing emitted after 12.6
    assert not p.in_echo_window(14.4, latency_s=1.5, tail_s=0.2)


def test_sample_clock_handles_bursty_arrival() -> None:
    c = SampleClock()
    t1 = c.stamp(1600, arrival=100.1)  # 100 ms of audio arriving at 100.1
    t2 = c.stamp(1600, arrival=100.25)  # late burst
    assert abs(t1 - 100.0) < 1e-6
    assert abs(t2 - 100.1) < 1e-6
    t3 = c.stamp(1600, arrival=103.0)  # stall -> re-anchor
    assert abs(t3 - 102.9) < 1e-6
