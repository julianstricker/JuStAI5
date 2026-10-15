#!/usr/bin/env python3
"""ERLE of WebRTC AEC3 vs. echo delay, with and without bulk delay compensation.

Synthetic speech-like signal, short room reverb, no near-end speech. Results are
documented in docs/AUDIO.md. Usage: uv run python scripts/measure_aec.py
"""

from __future__ import annotations

import numpy as np
from scipy.signal import butter, lfilter

from justai.audio.dsp import FRAME_10MS, SR
from justai.audio.echo import EchoCanceller

rng = np.random.default_rng(1)
N = SR * 12

# Speech-like reference: band-limited noise with a syllable envelope.
_b, _a = butter(4, [200 / (SR / 2), 3400 / (SR / 2)], "band")
_x = lfilter(_b, _a, rng.standard_normal(N))
_env = (np.sin(2 * np.pi * 3.5 * np.arange(N) / SR) > -0.2).astype(float)
REF = (_x * _env / np.max(np.abs(_x)) * 12000).astype(np.int16)

# Room impulse response: direct path plus a short reverb tail.
IR = rng.standard_normal(int(0.08 * SR)) * np.exp(-np.arange(int(0.08 * SR)) / (0.02 * SR)) * 0.05
IR[0] += 0.6


def erle(delay_s: float, compensate: bool) -> float:
    d = int(delay_s * SR)
    echo = np.convolve(REF.astype(float), IR)[:N]
    mic_f = np.zeros(N)
    mic_f[d:] = echo[: N - d]
    mic = (mic_f + rng.standard_normal(N) * 20).astype(np.int16)
    aec = EchoCanceller(aec=True, noise_suppression=False)
    outs = []
    for i in range(0, N - FRAME_10MS, FRAME_10MS):
        if compensate:
            j = i - d + EchoCanceller.RESIDUAL_DELAY_MS * SR // 1000
            r = REF[j:j + FRAME_10MS] if j >= 0 else np.zeros(FRAME_10MS, np.int16)
        else:
            r = REF[i:i + FRAME_10MS]
        outs.append(aec.process(mic[i:i + FRAME_10MS], r))
    out = np.concatenate(outs).astype(float)
    window = slice(6 * SR, 11 * SR)  # after convergence
    m = mic[window].astype(float)
    return float(10 * np.log10(np.mean(m**2) / (np.mean(out[window] ** 2) + 1e-9)))


def main() -> None:
    print("delay_s  ERLE_without_comp  ERLE_with_comp")
    for delay in (0.05, 0.2, 0.4, 0.6, 0.8, 1.2, 1.8):
        print(f"{delay:6.2f}  {erle(delay, False):8.1f} dB  {erle(delay, True):8.1f} dB")


if __name__ == "__main__":
    main()
