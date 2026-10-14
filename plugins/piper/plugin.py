"""Local text-to-speech with Piper."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from justai_sdk.audio import AudioChunk
from justai_sdk.plugin import HealthState, Plugin, PluginHealth
from justai_sdk.ports.ai import Locality, VoiceInfo


class PiperTTS:
    provider_id = "piper"
    locality = Locality.LOCAL

    def __init__(self, voices_dir: Path, length_scale: float = 1.0) -> None:
        self.voices_dir = voices_dir
        self.length_scale = length_scale
        self._voices: dict[str, Any] = {}
        self._lock = threading.Lock()

    def _available(self) -> dict[str, Path]:
        return {p.stem: p for p in sorted(self.voices_dir.glob("*.onnx"))
                if p.with_suffix(".onnx.json").exists()}

    def _pick(self, voice: str | None, language: str | None) -> str:
        available = self._available()
        if voice and voice in available:
            return voice
        lang = (language or "de")[:2]
        for name in available:
            if name.startswith(lang):
                return name
        if not available:
            raise RuntimeError(f"no piper voices in {self.voices_dir}")
        return next(iter(available))

    def _load(self, name: str) -> Any:
        with self._lock:
            if name not in self._voices:
                from piper import PiperVoice

                self._voices[name] = PiperVoice.load(str(self._available()[name]))
            return self._voices[name]

    async def synthesize(self, text: str, *, voice: str | None = None,
                         language: str | None = None) -> AsyncIterator[AudioChunk]:
        from piper import SynthesisConfig

        name = self._pick(voice, language)
        model = await asyncio.to_thread(self._load, name)
        rate = model.config.sample_rate
        cfg = SynthesisConfig(length_scale=self.length_scale)
        queue: asyncio.Queue[Any] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def produce() -> None:
            try:
                for chunk in model.synthesize(text, syn_config=cfg):  # one chunk per sentence
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.audio_int16_array)
            except Exception as exc:  # pragma: no cover - surfaced to the consumer
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=produce, daemon=True, name="piper-synth").start()
        while True:
            item = await queue.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield AudioChunk(item, rate)

    async def list_voices(self) -> list[VoiceInfo]:
        out = []
        for name, path in self._available().items():
            meta = json.loads(path.with_suffix(".onnx.json").read_text())
            lang = meta.get("language", {}).get("code", name.split("-")[0])
            out.append(VoiceInfo(id=name, name=name, language=lang))
        return out


class PiperPlugin(Plugin):
    async def setup(self) -> None:
        root = os.environ.get("JUSTAI_MODELS_DIR", "/models")
        self.tts = PiperTTS(Path(self.ctx.config.get("voices_dir") or f"{root}/piper"),
                            float(self.ctx.config.get("length_scale", 1.0)))
        self.ctx.register_provider("tts", self.tts)

    async def health(self) -> PluginHealth:
        voices = await self.tts.list_voices()
        if not voices:
            return PluginHealth(state=HealthState.FAILED, detail="no voices installed")
        return PluginHealth(metrics={"voices": float(len(voices))})
