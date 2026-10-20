"""Supervised background tasks.

Long-running loops (device connections, audio pipelines, vision workers) run under
a supervisor that restarts them with exponential backoff. A crash in one task is
logged and isolated; it never takes down other rooms or the API.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from justai.logging import get_logger

log = get_logger(__name__)


@dataclass
class TaskStatus:
    name: str
    running: bool = False
    restarts: int = 0
    last_error: str | None = None
    last_started: float | None = None


@dataclass
class _Entry:
    factory: Callable[[], Awaitable[None]]
    status: TaskStatus
    task: asyncio.Task[None] | None = None
    restart: bool = True
    backoff_s: float = 1.0
    max_backoff_s: float = 60.0
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)


STOP_TIMEOUT_S = 5.0


def await_chain(task: asyncio.Task[Any]) -> list[str]:
    """Where a task is waiting: the chain of awaited coroutines/generators (innermost last)."""
    out: list[str] = []
    obj: Any = task.get_coro()
    for _ in range(40):
        frame = getattr(obj, "cr_frame", None) or getattr(obj, "ag_frame", None) or getattr(obj, "gi_frame", None)
        if frame is not None:
            out.append(f"{frame.f_code.co_filename.rsplit('/', 2)[-1]}:{frame.f_lineno} {frame.f_code.co_name}")
        nxt = getattr(obj, "cr_await", None) or getattr(obj, "ag_await", None) or getattr(obj, "gi_yieldfrom", None)
        if nxt is None:
            if obj is not None and frame is None:
                out.append(repr(obj)[:120])
            break
        obj = nxt
    return out


class Supervisor:
    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}

    def start(
        self,
        name: str,
        factory: Callable[[], Awaitable[None]],
        *,
        restart: bool = True,
        max_backoff_s: float = 60.0,
    ) -> None:
        if name in self._entries:
            raise ValueError(f"task {name} already supervised")
        entry = _Entry(factory, TaskStatus(name), restart=restart, max_backoff_s=max_backoff_s)
        self._entries[name] = entry
        entry.task = asyncio.create_task(self._run(entry), name=f"supervised:{name}")

    async def _run(self, entry: _Entry) -> None:
        while not entry.stop_event.is_set():
            entry.status.running = True
            entry.status.last_started = time.monotonic()
            try:
                await entry.factory()
                entry.status.last_error = None
                if not entry.restart:
                    break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                entry.status.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("supervised task failed", task=entry.status.name, error=str(exc),
                            exc_info=True)
            finally:
                entry.status.running = False
            if not entry.restart or entry.stop_event.is_set():
                break
            # Reset backoff after a long healthy run.
            healthy_for = time.monotonic() - (entry.status.last_started or 0)
            if healthy_for > 120:
                entry.backoff_s = 1.0
            entry.status.restarts += 1
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(entry.stop_event.wait(), timeout=entry.backoff_s)
            entry.backoff_s = min(entry.backoff_s * 2, entry.max_backoff_s)

    async def stop(self, name: str, timeout_s: float = STOP_TIMEOUT_S) -> None:
        """Cancel a supervised task and wait (bounded) until it has ended.

        A task that does not end on cancellation is reported with the place it is stuck at
        instead of blocking the caller (disabling a camera once hung for minutes). The
        caller's own cancellation is not swallowed."""
        entry = self._entries.pop(name, None)
        if entry is None:
            return
        entry.stop_event.set()
        task = entry.task
        if task is None or task.done():
            return
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=timeout_s)
        if not done:
            log.warning("supervised task did not stop", task=name, waited_s=timeout_s,
                        stuck_at=await_chain(task))
            return
        if not task.cancelled():
            task.exception()  # retrieved: no "exception was never retrieved" warning

    async def stop_all(self) -> None:
        for name in list(self._entries):
            await self.stop(name)

    def status(self) -> list[TaskStatus]:
        return [e.status for e in self._entries.values()]

    def has(self, name: str) -> bool:
        return name in self._entries
