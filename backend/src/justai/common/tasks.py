"""Fire-and-forget tasks that are neither garbage-collected nor silently failing."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

from justai.logging import get_logger

log = get_logger(__name__)
_tasks: set[asyncio.Task[Any]] = set()


def _done(task: asyncio.Task[Any]) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.warning("background task failed", task=task.get_name(), error=str(task.exception()))


def spawn(coro: Coroutine[Any, Any, Any], name: str | None = None) -> asyncio.Task[Any]:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_done)
    return task
