"""Data retention: periodic deletion according to the configured retention periods."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete

from justai.db.models import ConversationSession, Job, Presentation, Sighting, StoredEvent, ToolExecution
from justai.logging import get_logger
from justai.system.settings import SystemSettings

if TYPE_CHECKING:
    from justai.container import Container

log = get_logger(__name__)


class RetentionService:
    def __init__(self, c: Container) -> None:
        self.c = c
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.c.jobs.register("system.retention", self._job)
        self._task = asyncio.create_task(self._loop(), name="retention")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        await asyncio.sleep(300)
        while True:
            with contextlib.suppress(Exception):
                await self.c.jobs.enqueue("system.retention", {}, dedup_key="system.retention")
            await asyncio.sleep(24 * 3600)

    async def _job(self, _: dict[str, Any]) -> None:
        await self.run()

    async def run(self) -> dict[str, int]:
        settings = SystemSettings.model_validate(await self.c.settings_store.get("system") or {})
        r = settings.retention
        now = datetime.now(UTC)
        counts: dict[str, int] = {}
        async with self.c.db.session() as s:
            for name, stmt in (
                ("events", delete(StoredEvent).where(StoredEvent.ts < now - timedelta(days=r.events_days))),
                ("sessions", delete(ConversationSession).where(
                    ConversationSession.started_at < now - timedelta(days=r.transcripts_days))),
                ("sightings", delete(Sighting).where(Sighting.last_seen < now - timedelta(days=r.sightings_days))),
                ("tool_executions", delete(ToolExecution).where(
                    ToolExecution.created_at < now - timedelta(days=r.tool_executions_days))),
                ("presentations", delete(Presentation).where(Presentation.created_at < now - timedelta(days=30))),
                ("jobs", delete(Job).where(Job.status.in_(["done", "failed"]),
                                           Job.created_at < now - timedelta(days=14))),
            ):
                result = await s.execute(stmt)
                counts[name] = int(result.rowcount or 0)  # type: ignore[attr-defined]
        log.info("retention cleanup", **counts)
        return counts
