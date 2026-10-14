"""Fixtures for audio tests with real models (Piper voices, openWakeWord).

Models are looked up in $JUSTAI_TEST_MODELS_DIR (layout: piper/*.onnx,
openwakeword/*.onnx) or /models (inside the core image). Tests are skipped if the
models are missing.
"""

from __future__ import annotations

import importlib.util
import os
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from justai.audio.dsp import resample

ROOT = Path(__file__).resolve().parents[3]


def models_dir() -> Path:
    return Path(os.environ.get("JUSTAI_TEST_MODELS_DIR", "/models"))


@lru_cache
def _voice(name: str):  # type: ignore[no-untyped-def]
    from piper import PiperVoice

    path = models_dir() / "piper" / f"{name}.onnx"
    if not path.exists():
        pytest.skip(f"piper voice {name} not available")
    return PiperVoice.load(str(path))


@lru_cache
def speak(text: str, voice: str = "de_DE-thorsten-medium") -> np.ndarray:
    v = _voice(voice)
    pcm = np.concatenate([c.audio_int16_array for c in v.synthesize(text)])
    return resample(pcm, v.config.sample_rate, 16000)


@pytest.fixture(scope="session")
def oww_provider():  # type: ignore[no-untyped-def]
    path = ROOT / "plugins" / "openwakeword" / "plugin.py"
    spec = importlib.util.spec_from_file_location("oww_plugin_under_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    mdir = models_dir() / "openwakeword"
    if not (mdir / "melspectrogram.onnx").exists():
        pytest.skip("openWakeWord models not available")
    return module.OpenWakeWordProvider(mdir)
