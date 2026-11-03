"""Shared helpers: clip augmentation and openWakeWord embeddings (used by train.py)."""
import os
import sys
from pathlib import Path

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(os.environ.get("WAKEWORD_WORK", ".")).resolve() / "pkg"))
from openwakeword.utils import AudioFeatures  # noqa: E402

ROOT = Path(os.environ.get("WAKEWORD_WORK", ".")).resolve()
SR = 16000
CLIP = 40000  # 2.5 s
WIN = 16
rng = np.random.default_rng(0)
torch.manual_seed(0)
torch.set_num_threads(8)

feat = AudioFeatures(melspec_model_path=str(ROOT / "models/melspectrogram.onnx"),
                     embedding_model_path=str(ROOT / "models/embedding_model.onnx"),
                     inference_framework="onnx", ncpu=2)


def load(kind):
    return list(np.load(ROOT / "clips" / f"{kind}.npy", allow_pickle=True))


def colored_noise(n, beta):
    f = np.fft.rfftfreq(n)
    f[0] = f[1]
    spec = (rng.standard_normal(len(f)) + 1j * rng.standard_normal(len(f))) / f ** (beta / 2)
    x = np.fft.irfft(spec, n)
    return (x / (np.abs(x).max() + 1e-9)).astype(np.float32)


def reverb(x):
    if rng.random() < 0.5:
        return x
    t60 = rng.uniform(0.1, 0.6)
    n = int(SR * t60)
    ir = rng.standard_normal(n) * np.exp(-6.9 * np.arange(n) / n)
    ir[0] = 1.0
    ir = ir.astype(np.float32) / np.abs(ir).sum() * 3
    return np.convolve(x, ir)[: len(x)].astype(np.float32)


def background(n, babble):
    r = rng.random()
    if r < 0.3:
        b = colored_noise(n, rng.choice([0.0, 1.0, 2.0]))
    elif r < 0.7 and babble:
        b = np.zeros(n, np.float32)
        for _ in range(rng.integers(1, 3)):
            s = babble[rng.integers(len(babble))]
            off = rng.integers(0, max(1, n - len(s)))
            seg = s[: n - off]
            b[off: off + len(seg)] += seg
    else:
        b = colored_noise(n, rng.choice([0.0, 1.0, 2.0])) + 0.3 * colored_noise(n, 2.0)
    return b


def make_clip(speech, babble, word_end_gap=None):
    """Place speech (or nothing) into a 2.5 s clip, add reverb / background / gain."""
    x = np.zeros(CLIP, np.float32)
    if speech is not None:
        s = reverb(speech * rng.uniform(0.15, 0.9))
        s = s[: CLIP - 4000]
        gap = word_end_gap if word_end_gap is not None else rng.integers(2000, 20000)
        end = max(len(s), CLIP - gap)
        end = min(end, CLIP)
        x[end - len(s): end] = s
    snr = rng.uniform(3, 30)
    b = background(CLIP, babble)
    sig = np.sqrt(np.mean(x ** 2)) + 1e-6 if speech is not None else 0.1
    b = b / (np.sqrt(np.mean(b ** 2)) + 1e-6) * sig / (10 ** (snr / 20))
    x = x + b
    x = np.clip(x * rng.uniform(0.5, 1.5), -1, 1)
    return (x * 32767).astype(np.int16)


def embed(clips):
    out = []
    for i in range(0, len(clips), 256):
        e = feat.embed_clips(np.stack(clips[i:i + 256]), batch_size=64)
        out.append(e)
    return np.concatenate(out)  # (N, frames, 96)


def positives(speech, babble, reps):
    clips = [make_clip(s, babble) for s in speech for _ in range(reps)]
    e = embed(clips)
    return e[:, -WIN:, :].astype(np.float32)


def negatives_windows(speech, babble, reps, stride=4):
    clips = [make_clip(s if rng.random() < 0.85 else None, babble, None) for s in speech for _ in range(reps)]
    e = embed(clips)
    wins = [e[:, i:i + WIN, :] for i in range(0, e.shape[1] - WIN + 1, stride)]
    return np.concatenate(wins).astype(np.float32)


def load_acav():
    parts = []
    for p in sorted((ROOT / "data").glob("acav_*.bin")):
        parts.append(np.fromfile(p, dtype="<f2").reshape(-1, WIN, 96))
    return np.concatenate(parts)


def build_cache(cache):
    """Embed positives (train / held-out) and synthetic negatives once; cached in `cache`."""
    pos_sp, adv_sp, neg_sp = load("pos"), load("adv"), load("neg")
    babble = list(neg_sp[:600])
    print("clips", len(pos_sp), len(adv_sp), len(neg_sp), flush=True)
    idx = rng.permutation(len(pos_sp))
    n_val = len(pos_sp) // 10
    val_i, tr_i = idx[:n_val], idx[n_val:]
    P_tr = positives([pos_sp[i] for i in tr_i], babble, reps=2)
    P_val = positives([pos_sp[i] for i in val_i], babble, reps=1)
    N_syn = np.concatenate([
        negatives_windows(adv_sp, babble, reps=3),
        negatives_windows(neg_sp[600:], babble, reps=1, stride=2),
        negatives_windows([None] * 400, babble, reps=1),
    ])
    np.savez(cache, P_tr=P_tr, P_val=P_val, N_syn=N_syn)
