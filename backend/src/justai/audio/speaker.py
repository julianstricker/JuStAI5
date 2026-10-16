"""Speaker embeddings ("is this the same voice as before?").

Used to decide whether a new wakeword continues the previous conversation (same
speaker) or starts a fresh one. Embeddings stay in memory only and are compared
with each other; they are not stored and not linked to a person (no enrolment).

Model: WeSpeaker ResNet34 trained on VoxCeleb (ONNX, 256-dim output), fed with
Kaldi-compatible 80-bin log-mel filterbank features with per-utterance mean
normalisation - the same front-end WeSpeaker was trained with.
"""

from __future__ import annotations

import threading
from functools import lru_cache
from pathlib import Path

import numpy as np

from justai.audio.dsp import SR

FRAME = 400  # 25 ms
SHIFT = 160  # 10 ms
NFFT = 512
NUM_MELS = 80
MIN_SECONDS = 1.0


@lru_cache(maxsize=1)
def _mel_banks() -> np.ndarray:
    def mel(f: np.ndarray | float) -> np.ndarray:
        return 1127.0 * np.log(1.0 + np.asarray(f) / 700.0)

    low, high = mel(20.0), mel(SR / 2)
    centers = np.linspace(low, high, NUM_MELS + 2)
    bins = mel(np.arange(NFFT // 2) * SR / NFFT)
    banks = np.zeros((NUM_MELS, NFFT // 2 + 1))
    for m in range(NUM_MELS):
        left, center, right = centers[m], centers[m + 1], centers[m + 2]
        up = (bins - left) / (center - left)
        down = (right - bins) / (right - center)
        banks[m, : NFFT // 2] = np.maximum(0.0, np.minimum(up, down))
    return banks


@lru_cache(maxsize=1)
def _povey_window() -> np.ndarray:
    return np.power(0.5 - 0.5 * np.cos(2 * np.pi * np.arange(FRAME) / (FRAME - 1)), 0.85)


def fbank(pcm16k: np.ndarray) -> np.ndarray:
    """Kaldi-style log-mel filterbank (dither 0, snip edges) with mean normalisation."""
    x = pcm16k.astype(np.float64)  # int16 scale, as the model expects (normalize_samples=0)
    n = 1 + (x.size - FRAME) // SHIFT
    if n <= 0:
        return np.zeros((0, NUM_MELS), np.float32)
    idx = np.arange(FRAME)[None, :] + SHIFT * np.arange(n)[:, None]
    frames = x[idx]
    frames -= frames.mean(axis=1, keepdims=True)
    emphasized = frames.copy()
    emphasized[:, 1:] -= 0.97 * frames[:, :-1]
    emphasized[:, 0] -= 0.97 * frames[:, 0]
    spectrum = np.abs(np.fft.rfft(emphasized * _povey_window(), NFFT)) ** 2
    feats = np.log(np.maximum(spectrum @ _mel_banks().T, np.finfo(np.float32).eps))
    feats -= feats.mean(axis=0, keepdims=True)
    out: np.ndarray = feats.astype(np.float32)
    return out


class SpeakerEmbedder:
    def __init__(self, model_path: Path) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self._session = ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
        self._lock = threading.Lock()

    def embed(self, pcm16k: np.ndarray) -> np.ndarray | None:
        """L2-normalised voice embedding of (mostly) speech audio; None if too short."""
        if pcm16k.size < MIN_SECONDS * SR:
            return None
        feats = fbank(pcm16k)[None, :, :]
        with self._lock:
            emb = self._session.run(None, {"feats": feats})[0][0]
        norm = float(np.linalg.norm(emb))
        return (emb / norm).astype(np.float32) if norm > 0 else None


def similarity(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))
