"""openWakeWord provider (ONNX inference, local)."""

from __future__ import annotations

import os
import re
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


MAX_CUSTOM_MODEL_BYTES = 20_000_000
_CUSTOM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{1,40}$")


def validate_wakeword_model(data: bytes) -> None:
    """Accept only openWakeWord classifier models: input [1, n, 96] embeddings, output [1, 1]."""
    import onnxruntime as ort

    if len(data) > MAX_CUSTOM_MODEL_BYTES:
        raise ValueError("model file too large")
    try:
        session = ort.InferenceSession(data, providers=["CPUExecutionProvider"])
    except Exception as exc:
        raise ValueError(f"not a valid ONNX file: {exc}") from exc
    inputs, outputs = session.get_inputs(), session.get_outputs()
    shape_in = inputs[0].shape if len(inputs) == 1 else None
    shape_out = outputs[0].shape if len(outputs) == 1 else None
    if not shape_in or len(shape_in) != 3 or shape_in[-1] != 96 or not shape_out or shape_out[-1] != 1:
        raise ValueError("not an openWakeWord model (expected input [1, n, 96] and output [1, 1])")


class OpenWakeWordProvider:
    provider_id = "openwakeword"

    def __init__(self, models_dir: Path, custom_dir: Path | None = None) -> None:
        self.models_dir = models_dir  # bundled models + feature models (read-only image)
        self.custom_dir = custom_dir  # uploaded models (persistent volume)
        self._lock = threading.Lock()

    def _models(self) -> dict[str, Path]:
        found: dict[str, Path] = {}
        dirs = [self.models_dir] + ([self.custom_dir] if self.custom_dir else [])
        for d in dirs:
            for p in sorted(d.glob("*.onnx")) if d.exists() else []:
                if p.name in FEATURE_MODELS:
                    continue
                found[model_id(p)] = p
        return found

    def list_models(self) -> list[WakewordModelInfo]:
        return [WakewordModelInfo(id=mid, name=mid + (" (eigenes)" if path.parent == self.custom_dir else ""),
                                  phrase=PHRASES.get(mid, mid.replace("_", " ").title()),
                                  languages=["en"] if mid in PHRASES else [])
                for mid, path in self._models().items()]

    def install_model(self, name: str, data: bytes) -> str:
        """Store an uploaded wakeword model; returns its id (the file name without .onnx)."""
        if self.custom_dir is None:
            raise ValueError("no directory for own models configured")
        mid = name.lower().removesuffix(".onnx").replace("-", "_").replace(" ", "_")
        if not _CUSTOM_NAME_RE.match(mid):
            raise ValueError("name only of lower-case letters, digits and _ (e.g. hey_justi)")
        if mid in self._models() and (self.models_dir / f"{mid}.onnx").exists():
            raise ValueError(f"{mid} is a bundled model")
        validate_wakeword_model(data)
        self.custom_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.custom_dir / f".{mid}.upload"
        tmp.write_bytes(data)
        tmp.replace(self.custom_dir / f"{mid}.onnx")
        return mid

    def remove_model(self, mid: str) -> None:
        path = self._models().get(mid)
        if path is None or self.custom_dir is None or path.parent != self.custom_dir:
            raise ValueError("only own models can be deleted")
        path.unlink()

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
        root = os.environ.get("JUSTAI_MODELS_DIR", "/models")
        models_dir = Path(self.ctx.config.get("models_dir") or f"{root}/openwakeword")
        custom_dir = Path(os.environ.get("JUSTAI_DATA_DIR", "/data")) / "wakewords"
        self.provider = OpenWakeWordProvider(models_dir, custom_dir)
        self.ctx.register_provider("wakeword", self.provider)

    async def health(self) -> PluginHealth:
        missing = [f for f in FEATURE_MODELS if not (self.provider.models_dir / f).exists()]
        if missing:
            return PluginHealth(state=HealthState.FAILED, detail=f"missing models: {missing}")
        if not self.provider.list_models():
            return PluginHealth(state=HealthState.DEGRADED, detail="no wakeword models installed")
        return PluginHealth()
