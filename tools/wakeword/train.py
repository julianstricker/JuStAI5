"""Train the wakeword classifier and export it as ONNX.

Negatives: ACAV100M features, synthetic speech (pos/adv/adv2/neg clips) and 60 % of the real
validation recording; the other 40 % is held out to measure false activations per hour.
Output: $WAKEWORD_WORK/<MODEL_NAME>.onnx (default hey_justi)."""
import os
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch
from torch import nn

ROOT = Path(os.environ.get("WAKEWORD_WORK", ".")).resolve()
sys.path.insert(0, str(Path(__file__).parent))
import features as T  # noqa: E402  (feature extractor + clip helpers)

MODEL_NAME = os.environ.get("MODEL_NAME", "hey_justi")
WIN = 16
rng = np.random.default_rng(1)
torch.manual_seed(1)
torch.set_num_threads(8)


def events(scores, th, refr=19):
    idx = np.flatnonzero(scores > th)
    if len(idx) == 0:
        return 0
    return int(1 + (np.diff(idx) > refr).sum())


class Net(nn.Module):
    def __init__(self, hidden=96, drop=0.3):
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(), nn.Dropout(0.1), nn.Linear(WIN * 96, hidden), nn.LayerNorm(hidden), nn.ReLU(),
            nn.Dropout(drop), nn.Linear(hidden, hidden), nn.LayerNorm(hidden), nn.ReLU(),
            nn.Dropout(drop), nn.Linear(hidden, 1), nn.Sigmoid())

    def forward(self, x):
        return self.net(x)


def main():
    cache = ROOT / "feat_cache.npz"
    if not cache.exists():
        T.build_cache(cache)
    c = np.load(cache)
    P_tr, P_val, N_syn = c["P_tr"], c["P_val"], c["N_syn"]
    cache2 = ROOT / "feat_cache_adv2.npy"
    if not cache2.exists():
        adv2 = T.load("adv2")
        babble = T.load("neg")[:600]
        np.save(cache2, T.negatives_windows(adv2, babble, reps=2, stride=2))
    A2 = np.load(cache2)
    cut2 = int(len(A2) * 0.9)
    A2_tr, A2_ho = A2[:cut2], A2[cut2:]
    print("adv2 windows", A2_tr.shape, A2_ho.shape, flush=True)
    N_acav = np.concatenate([np.fromfile(p, dtype="<f2").reshape(-1, WIN, 96)
                             for p in sorted((ROOT / "data").glob("acav_*.bin"))])
    frames = np.load(ROOT / "data/validation_set_features.npy").astype(np.float32)
    V = np.lib.stride_tricks.sliding_window_view(frames, (WIN, 96)).reshape(-1, WIN, 96)
    cut = int(len(V) * 0.6)
    V_a, V_b = np.ascontiguousarray(V[:cut]), np.ascontiguousarray(V[cut + WIN:])
    hours_b = len(V_b) * 0.08 / 3600
    print("valA", V_a.shape, "valB", V_b.shape, round(hours_b, 2), "h", flush=True)

    model = Net()
    steps = 9000
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=1e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1.5e-3, total_steps=steps)
    bce = nn.BCELoss(reduction="none")
    Pt, Ns = torch.from_numpy(P_tr), torch.from_numpy(N_syn)
    VaT = torch.from_numpy(V_a)
    A2T = torch.from_numpy(A2_tr)

    def batch():
        p = Pt[torch.randint(len(Pt), (96,))]
        p = p * (1 + 0.03 * torch.randn(len(p), 1, 96))  # feature jitter against overfitting to TTS
        ns = Ns[torch.randint(len(Ns), (96,))]
        na = torch.from_numpy(N_acav[np.sort(rng.integers(0, len(N_acav), 128))].astype(np.float32))
        nv = VaT[torch.randint(len(VaT), (192,))]
        n2 = A2T[torch.randint(len(A2T), (96,))]
        x = torch.cat([p, ns, na, nv, n2])
        y = torch.cat([torch.ones(len(p)), torch.zeros(len(ns) + len(na) + len(nv) + len(n2))])
        w = torch.cat([torch.ones(len(p)), torch.full((len(ns),), 1.5), torch.ones(len(na)),
                       torch.full((len(nv),), 2.0), torch.full((len(n2),), 2.5)])
        return x, y, w

    def evaluate():
        model.eval()
        with torch.no_grad():
            pv = model(torch.from_numpy(P_val)).squeeze(1).numpy()
            fb = np.concatenate([model(torch.from_numpy(V_b[i:i + 8192])).squeeze(1).numpy()
                                 for i in range(0, len(V_b), 8192)])
            a2 = model(torch.from_numpy(A2_ho)).squeeze(1).numpy()
        model.train()
        return {"names-fp@0.5": round(float((a2 > 0.5).mean()), 4), "names-fp@0.8": round(float((a2 > 0.8).mean()), 4)} | {f"recall@{t}": round(float((pv > t).mean()), 3) for t in (0.5, 0.8)} | \
               {f"ev/h@{t}": round(events(fb, t) / hours_b, 2) for t in (0.5, 0.8, 0.95)}

    best, best_state = None, None
    for step in range(1, steps + 1):
        x, y, w = batch()
        loss = (bce(model(x).squeeze(1), y) * w).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if step % 750 == 0:
            m = evaluate()
            score = m["recall@0.8"] - 0.03 * m["ev/h@0.8"] - 5 * m["names-fp@0.8"]
            print(step, round(loss.item(), 4), m, flush=True)
            if step >= steps // 3 and (best is None or score > best):
                best, best_state = score, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    model.eval()
    print("final", evaluate(), flush=True)
    out = ROOT / f"{MODEL_NAME}.onnx"
    torch.onnx.export(model, torch.zeros(1, WIN, 96), str(out), input_names=["x.1"], output_names=["out"],
                      opset_version=13, dynamo=False)
    s = ort.InferenceSession(str(out))
    print("exported", out, s.get_inputs()[0].shape, s.get_outputs()[0].shape)


if __name__ == "__main__":
    main()
