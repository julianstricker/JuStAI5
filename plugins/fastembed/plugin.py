"""Local multilingual embeddings with fastembed."""

from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

from justai_sdk.plugin import Plugin
from justai_sdk.ports.ai import Locality

DIMENSIONS = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": 384,
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2": 768,
    "intfloat/multilingual-e5-large": 1024,
}


class FastEmbedProvider:
    provider_id = "fastembed"
    locality = Locality.LOCAL

    def __init__(self, model: str, cache_dir: str | None) -> None:
        self.model_id = model
        self.dimension = DIMENSIONS.get(model, 384)
        self.cache_dir = cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.model_id, cache_dir=self.cache_dir)
            return self._model

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._load().embed(texts)]

    async def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]:
        return await asyncio.to_thread(self._embed, texts)


class FastEmbedPlugin(Plugin):
    async def setup(self) -> None:
        self.provider = FastEmbedProvider(self.ctx.config.get("model", next(iter(DIMENSIONS))),
                                          self.ctx.config.get("cache_dir")
                                          or os.path.join(os.environ.get("JUSTAI_MODELS_DIR", "/models"), "fastembed"))
        self.ctx.register_provider("embedding", self.provider)

    async def start(self) -> None:
        fut = asyncio.get_running_loop().run_in_executor(None, self.provider._load)
        fut.add_done_callback(lambda f: f.exception() and self.ctx.logger.error(
            "embedding model could not be loaded: %s", f.exception()))
