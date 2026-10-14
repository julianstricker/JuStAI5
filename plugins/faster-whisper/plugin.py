"""Local speech-to-text with faster-whisper."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

import numpy as np
from justai_sdk.audio import AudioChunk
from justai_sdk.plugin import Plugin, PluginHealth
from justai_sdk.ports.ai import Locality, Transcription


def models_dir(sub: str) -> str:
    return os.path.join(os.environ.get("JUSTAI_MODELS_DIR", "/models"), sub)


class FasterWhisperSTT:
    provider_id = "faster-whisper"
    locality = Locality.LOCAL

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                device = self.config.get("device", "auto")
                self._model = WhisperModel(
                    self.config.get("model", "small"), device=device,
                    compute_type=self.config.get("compute_type", "int8"),
                    download_root=self.config.get("download_root") or models_dir("whisper"))
            return self._model

    def _run(self, audio: AudioChunk, language: str | None, prompt: str | None) -> Transcription:
        if audio.sample_rate != 16000:
            raise ValueError("faster-whisper expects 16 kHz audio")
        model = self._load()
        samples = audio.pcm.astype(np.float32) / 32768.0
        segments, info = model.transcribe(
            samples, language=language, beam_size=int(self.config.get("beam_size", 1)),
            initial_prompt=prompt, vad_filter=False, condition_on_previous_text=False)
        segs = list(segments)
        text = " ".join(s.text.strip() for s in segs).strip()
        no_speech = float(np.mean([s.no_speech_prob for s in segs])) if segs else 1.0
        return Transcription(text=text, language=info.language,
                             language_probability=info.language_probability,
                             no_speech_probability=no_speech, duration_s=audio.duration_s)

    async def transcribe(self, audio: AudioChunk, *, language: str | None = None,
                         prompt: str | None = None) -> Transcription:
        return await asyncio.to_thread(self._run, audio, language, prompt)

    def warm_up(self) -> None:
        self._load()


class FasterWhisperPlugin(Plugin):
    async def setup(self) -> None:
        self.stt = FasterWhisperSTT(self.ctx.config)
        self.ctx.register_provider("stt", self.stt)

    async def start(self) -> None:
        # Load the model in the background so the first utterance is fast.
        self._warm = asyncio.get_running_loop().run_in_executor(None, self.stt.warm_up)
        self._warm.add_done_callback(self._warm_done)

    def _warm_done(self, fut: asyncio.Future[None]) -> None:
        if fut.exception() is not None:
            self.ctx.logger.error("whisper model could not be loaded: %s", fut.exception())

    async def health(self) -> PluginHealth:
        return PluginHealth(metrics={"loaded": 1.0 if self.stt._model is not None else 0.0})
