"""Streaming voice activity detection with Silero VAD (ONNX, CPU).

The model file ships with faster-whisper, so no extra download is needed.
"""

from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
import onnxruntime
from justai_sdk.audio import Int16Array

from justai.audio.dsp import Framer

WINDOW = 512  # samples @16 kHz (32 ms)
CONTEXT = 64


def default_model_path() -> Path:
    import faster_whisper

    return Path(faster_whisper.__file__).parent / "assets" / "silero_vad_v6.onnx"


class _SharedSession:
    """One ONNX session shared by all endpoints (state is kept per stream)."""

    _lock = threading.Lock()
    _session: onnxruntime.InferenceSession | None = None

    @classmethod
    def get(cls, path: Path) -> onnxruntime.InferenceSession:
        with cls._lock:
            if cls._session is None:
                opts = onnxruntime.SessionOptions()
                opts.inter_op_num_threads = 1
                opts.intra_op_num_threads = 1
                opts.log_severity_level = 4
                cls._session = onnxruntime.InferenceSession(
                    str(path), sess_options=opts, providers=["CPUExecutionProvider"])
            return cls._session


class SileroVad:
    """Per-stream VAD state. ``process`` accepts any chunk size and returns the
    probability of the most recent 32 ms window (or the previous value)."""

    def __init__(self, model_path: Path | None = None) -> None:
        self._session = _SharedSession.get(model_path or default_model_path())
        self._framer = Framer(WINDOW)
        self.reset()

    def reset(self) -> None:
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._context = np.zeros(CONTEXT, dtype=np.float32)
        self._framer.reset()
        self.probability = 0.0

    def process(self, pcm16k: Int16Array) -> float:
        for frame in self._framer.push(pcm16k):
            audio = frame.astype(np.float32) / 32768.0
            x = np.concatenate([self._context, audio])[None, :]
            out, self._h, self._c = self._session.run(
                None, {"input": x, "h": self._h, "c": self._c})
            self._context = audio[-CONTEXT:]
            self.probability = float(np.asarray(out).reshape(-1)[0])
        return self.probability
