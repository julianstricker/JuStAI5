"""Durable job queue on PostgreSQL (``FOR UPDATE SKIP LOCKED``).

Used for work that must survive restarts: automation runs, memory extraction,
consolidation, retention clean-up. Handlers are registered per job ``kind``.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert

from justai.db.engine import Database
from justai.db.models import Job
from justai.logging import get_logger

log = get_logger(__name__)

JobHandler = Callable[[dict[str, Any]], Awaitable[None]]


class RetryLater(Exception):
    def __init__(self, delay_s: float, reason: str = "") -> None:
        super().__init__(reason)
        self.delay_s = delay_s


class JobQueue:
    def __init__(self, db: Database, *, workers: int = 2, poll_interval_s: float = 1.0,
                 stale_after_s: float = 600) -> None:
        self.db = db
        self.workers = workers
        self.poll_interval_s = poll_interval_s
        self.stale_after_s = stale_after_s
        self._handlers: dict[str, JobHandler] = {}
        self._tasks: list[asyncio.Task[None]] = []
        self._wake = asyncio.Event()

    def register(self, kind: str, handler: JobHandler) -> None:
        self._handlers[kind] = handler

    async def enqueue(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        priority: int = 1,
        delay_s: float = 0,
        max_attempts: int = 3,
        dedup_key: str | None = None,
    ) -> str | None:
        run_at = datetime.now(UTC) + timedelta(seconds=delay_s)
        async with self.db.session() as s:
            stmt = (
                insert(Job)
                .values(kind=kind, payload=payload, priority=priority, run_at=run_at,
                        max_attempts=max_attempts, dedup_key=dedup_key)
                .on_conflict_do_nothing()
                .returning(Job.id)
            )
            job_id = (await s.execute(stmt)).scalar_one_or_none()
        self._wake.set()
        return job_id

    async def start(self) -> None:
        await self._recover_stale()
        for i in range(self.workers):
            self._tasks.append(asyncio.create_task(self._worker(i), name=f"job-worker-{i}"))

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await t
        self._tasks.clear()

    async def _recover_stale(self) -> None:
        """Jobs left 'running' by a crash are made pending again (restart recovery)."""
        cutoff = datetime.now(UTC) - timedelta(seconds=5)
        async with self.db.session() as s:
            result = await s.execute(
                update(Job)
                .where(Job.status == "running", Job.locked_at < cutoff)
                .values(status="pending", locked_at=None)
            )
        if result.rowcount:  # type: ignore[attr-defined]
            log.info("recovered interrupted jobs", count=result.rowcount)  # type: ignore[attr-defined]

    async def _claim(self) -> Job | None:
        async with self.db.session() as s:
            stmt = (
                select(Job)
                .where(Job.status == "pending", Job.run_at <= text("now()"),
                       Job.kind.in_(list(self._handlers)))
                .order_by(Job.priority.desc(), Job.run_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            job = (await s.scalars(stmt)).first()
            if job is None:
                return None
            job.status = "running"
            job.attempts += 1
            job.locked_at = datetime.now(UTC)
            return job

    async def _finish(self, job_id: str, *, status: str, error: str | None = None,
                      retry_in_s: float | None = None) -> None:
        values: dict[str, Any] = {"status": status, "last_error": error, "locked_at": None}
        if status in ("done", "failed"):
            values["finished_at"] = datetime.now(UTC)
        if retry_in_s is not None:
            values["run_at"] = datetime.now(UTC) + timedelta(seconds=retry_in_s)
        async with self.db.session() as s:
            await s.execute(update(Job).where(Job.id == job_id).values(**values))

    async def run_once(self) -> bool:
        """Process at most one job. Returns True if a job was processed."""
        job = await self._claim()
        if job is None:
            return False
        handler = self._handlers[job.kind]
        try:
            await handler(job.payload)
        except RetryLater as exc:
            await self._finish(job.id, status="pending", error=str(exc), retry_in_s=exc.delay_s)
        except Exception as exc:
            final = job.attempts >= job.max_attempts
            log.warning("job failed", kind=job.kind, job_id=job.id, attempt=job.attempts,
                        final=final, error=str(exc))
            await self._finish(
                job.id,
                status="failed" if final else "pending",
                error=f"{type(exc).__name__}: {exc}",
                retry_in_s=None if final else min(300.0, 2.0 ** job.attempts),
            )
        else:
            await self._finish(job.id, status="done")
        return True

    async def _worker(self, index: int) -> None:
        while True:
            try:
                processed = await self.run_once()
            except Exception as exc:
                log.error("job worker error", worker=index, error=str(exc))
                processed = False
            if not processed:
                self._wake.clear()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval_s)
