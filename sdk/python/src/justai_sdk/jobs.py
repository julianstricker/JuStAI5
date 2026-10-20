"""Periodic background jobs of plugins (polling an API, watching a value, ...)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

JobCallback = Callable[[], Awaitable[None]]

SANDBOX_MIN_INTERVAL_S = 60.0
SANDBOX_MAX_JOBS = 5


Logger = logging.Logger | logging.LoggerAdapter[logging.Logger]


async def run_periodic(seconds: float, callback: JobCallback, logger: Logger, name: str,
                       timeout_s: float | None = None) -> None:
    """Run ``callback`` now and then every ``seconds``; errors are logged, the job goes on."""
    while True:
        try:
            await asyncio.wait_for(callback(), timeout=timeout_s or max(10.0, seconds))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # a failing poll must not end the job
            logger.warning("background job %s failed: %s", name, exc)
        await asyncio.sleep(seconds)
