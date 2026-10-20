"""Stopping a supervised task is bounded and does not swallow the caller's cancellation."""

import asyncio
import time

import pytest

from justai.common.supervisor import Supervisor, await_chain


async def stubborn() -> None:
    """Ignores cancellation for a while (like a stuck cleanup)."""
    try:
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await asyncio.sleep(2.0)  # cleanup that takes too long
        raise


async def test_stop_waits_bounded_for_a_task_that_ignores_cancellation() -> None:
    sup = Supervisor()
    sup.start("stuck", stubborn, restart=False)
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    await sup.stop("stuck", timeout_s=0.2)
    assert time.monotonic() - t0 < 1.0
    assert not sup.has("stuck")


async def test_stop_of_a_cooperative_task_is_quick() -> None:
    sup = Supervisor()
    sup.start("ok", lambda: asyncio.sleep(3600), restart=False)
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    await sup.stop("ok")
    assert time.monotonic() - t0 < 0.5


async def test_cancelling_the_caller_of_stop_is_not_swallowed() -> None:
    sup = Supervisor()
    sup.start("stuck", stubborn, restart=False)
    await asyncio.sleep(0.05)
    caller = asyncio.create_task(sup.stop("stuck", timeout_s=10))
    await asyncio.sleep(0.1)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller


async def test_await_chain_names_the_place_a_task_waits_at() -> None:
    async def inner() -> None:
        await asyncio.sleep(3600)

    async def outer() -> None:
        await inner()

    task = asyncio.create_task(outer())
    await asyncio.sleep(0.01)
    chain = await_chain(task)
    assert any("outer" in f for f in chain) and any("inner" in f for f in chain)
    task.cancel()
