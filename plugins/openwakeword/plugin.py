"""openWakeWord provider (ONNX inference, local)."""

from __future__ import annotations

import os
import threading
from pathlib import Path

from justai_sdk.audio import Int16Array
from justai_sdk.plugin import HealthState, Plugin, PluginHealth
from justai_sdk.ports.wakeword import WakeDetection, WakewordModelInfo

FEATURE_MODELS = ("melspectrogram.onnx", "embedding_model.onnx")
PHRASES = {
    "hey_jarvis": "Hey Jarvis",
    "alexa": "Alexa",
    "hey_mycroft": "Hey Mycroft",
    "hey_rhasspy": "Hey Rhasspy",
    "ok_nabu": "Okay Nabu",
}


def model_id(path: Path) -> str:
    name = path.stem
    for suffix in ("_v0.1", "_v0.2", "_v1"):
        name = name.removesuffix(suffix)
    return name


class OpenWakeWordDetector:
    frame_samples = 1280  # 80 ms @ 16 kHz

    def __init__(self, models_dir: Path, model_paths: dict[str, Path]) -> None:
        from openwakeword.model import Model

        self._ids = {str(p.stem): mid for mid, p in model_paths.items()}
        self._model = Model(
            wakeword_models=[str(p) for p in model_paths.values()],
            melspec_model_path=str(models_dir / "melspectrogram.onnx"),
            embedding_model_path=str(models_dir / "embedding_model.onnx"),
            inference_framework="onnx",
        )

    def process(self, pcm16k: Int16Array) -> list[WakeDetection]:
        scores = self._model.predict(pcm16k)
        return [WakeDetection(model=self._ids.get(name, name), score=float(score))
                for name, score in scores.items() if score >= 0.01]

    def reset(self) -> None:
        self._model.reset()


class OpenWakeWordProvider:
    provider_id = "openwakeword"

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._lock = threading.Lock()

    def _models(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        for p in sorted(self.models_dir.glob("*.onnx")):
            if p.name in FEATURE_MODELS:
                continue
            found[model_id(p)] = p
        return found

    def list_models(self) -> list[WakewordModelInfo]:
        return [WakewordModelInfo(id=mid, name=mid, phrase=PHRASES.get(mid, mid.replace("_", " ")),
                                  languages=["en"])
                for mid in self._models()]

    def create_detector(self, models: list[str]) -> OpenWakeWordDetector:
        available = self._models()
        selected = {m: available[m] for m in models if m in available}
        if not selected:
            raise ValueError(f"none of the wakeword models {models} is installed "
                             f"(available: {sorted(available)})")
        with self._lock:  # model construction is not thread-safe
            return OpenWakeWordDetector(self.models_dir, selected)


class OpenWakeWordPlugin(Plugin):
    async def setup(self) -> None:
        models_dir = Path(os.environ.get("JUSTAI_OWW_MODELS_DIR")
                          or self.ctx.config.get("models_dir") or "/models/openwakeword")
        self.provider = OpenWakeWordProvider(models_dir)
        self.ctx.register_provider("wakeword", self.provider)

    async def health(self) -> PluginHealth:
        missing = [f for f in FEATURE_MODELS if not (self.provider.models_dir / f).exists()]
        if missing:
            return PluginHealth(state=HealthState.FAILED, detail=f"missing models: {missing}")
        if not self.provider.list_models():
            return PluginHealth(state=HealthState.DEGRADED, detail="no wakeword models installed")
        return PluginHealth()
