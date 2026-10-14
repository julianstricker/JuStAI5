"""Persistence and querying of durable events."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any

from justai_sdk.events import Event
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from justai.common.redact import redact
from justai.db.engine import Database
from justai.db.models import StoredEvent
from justai.logging import get_logger

log = get_logger(__name__)


def _row(event: Event) -> dict[str, Any]:
    return {
        "id": event.id,
        "type": event.type,
        "version": event.version,
        "ts": event.timestamp,
        "source": event.source.model_dump(exclude_none=True),
        "payload": redact(event.payload),
        "room_id": event.source.room_id,
        "device_id": event.source.device_id,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "hop": event.hop,
        "priority": int(event.priority),
        "sensitivity": str(event.sensitivity),
    }


class EventStore:
    """Writes durable events in small batches (flush every 200 ms or 100 events)."""

    def __init__(self, db: Database, *, batch_size: int = 100, flush_interval_s: float = 0.2):
        self.db = db
        self.batch_size = batch_size
        self.flush_interval_s = flush_interval_s
        self._pending: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()
        self._flusher: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._flusher = asyncio.create_task(self._flush_loop(), name="event-store-flush")

    async def stop(self) -> None:
        if self._flusher:
            self._flusher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._flusher
        await self.flush()

    async def append(self, event: Event) -> None:
        async with self._lock:
            self._pending.append(_row(event))
            full = len(self._pending) >= self.batch_size
        if full:
            await self.flush()

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(self.flush_interval_s)
            try:
                await self.flush()
            except Exception as exc:
                log.error("event flush failed", error=str(exc))

    async def flush(self) -> None:
        async with self._lock:
            rows, self._pending = self._pending, []
        if not rows:
            return
        async with self.db.session() as s:
            await s.execute(insert(StoredEvent).values(rows).on_conflict_do_nothing())

    async def query(
        self,
        *,
        types: list[str] | None = None,
        type_prefix: str | None = None,
        room_id: str | None = None,
        correlation_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        payload_contains: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[StoredEvent]:
        await self.flush()
        stmt = select(StoredEvent).order_by(StoredEvent.ts.desc()).limit(min(limit, 1000))
        if types:
            stmt = stmt.where(StoredEvent.type.in_(types))
        if type_prefix:
            stmt = stmt.where(StoredEvent.type.startswith(type_prefix))
        if room_id:
            stmt = stmt.where(StoredEvent.room_id == room_id)
        if correlation_id:
            stmt = stmt.where(StoredEvent.correlation_id == correlation_id)
        if since:
            stmt = stmt.where(StoredEvent.ts >= since)
        if until:
            stmt = stmt.where(StoredEvent.ts <= until)
        if payload_contains:
            stmt = stmt.where(StoredEvent.payload.contains(payload_contains))
        async with self.db.session() as s:
            return list((await s.scalars(stmt)).all())

    async def purge_older_than(self, cutoff: datetime) -> int:
        async with self.db.session() as s:
            result = await s.execute(delete(StoredEvent).where(StoredEvent.ts < cutoff))
            return int(result.rowcount or 0)  # type: ignore[attr-defined]
