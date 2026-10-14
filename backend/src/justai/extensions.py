"""Feature modules built on top of the core services.

Each extension is an object with optional ``start()``/``stop()`` coroutines. They
are constructed here so that the container stays small and each feature can later
be moved into its own process without touching the others.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from justai.output.speech import SpeechService

if TYPE_CHECKING:
    from justai.container import Container


async def build_extensions(c: Container) -> dict[str, Any]:
    ext: dict[str, Any] = {}
    ext["speech"] = SpeechService(c.output, c.audio, c.ai)
    return ext
