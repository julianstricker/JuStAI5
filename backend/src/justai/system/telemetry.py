"""Live telemetry (audio levels, VAD, gate state, ...) for the diagnostics UI.

Telemetry is high-frequency and ephemeral; it is kept separate from the event bus
and never persisted.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any


class TelemetryHub:
    def __init__(self) -> None:
        self._latest: dict[str, tuple[float, Any]] = {}
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def publish(self, topic: str, data: Any) -> None:
        self._latest[topic] = (time.time(), data)
        if not self._subscribers:
            return
        message = {"topic": topic, "ts": time.time(), "data": data}
        for q in list(self._subscribers):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(message)

    def snapshot(self, prefix: str = "") -> dict[str, Any]:
        return {k: {"ts": ts, "data": v} for k, (ts, v) in self._latest.items() if k.startswith(prefix)}

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)
