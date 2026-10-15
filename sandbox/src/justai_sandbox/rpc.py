"""Bidirectional JSON-lines RPC over a pair of async streams."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Awaitable, Callable
from typing import Any

Handler = Callable[[str, dict[str, Any]], Awaitable[Any]]


class RpcError(Exception):
    pass


class RpcPeer:
    def __init__(self, reader: asyncio.StreamReader, writer: Any, handler: Handler) -> None:
        self.reader = reader
        self.writer = writer  # object with write(bytes) and drain()
        self.handler = handler
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._task: asyncio.Task[None] | None = None
        self._serving: set[asyncio.Task[None]] = set()

    def start(self) -> None:
        self._task = asyncio.create_task(self._read_loop())

    async def call(self, method: str, params: dict[str, Any], timeout: float = 60.0) -> Any:
        msg_id = next(self._ids)
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await self._send({"id": msg_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(msg_id, None)

    async def _send(self, message: dict[str, Any]) -> None:
        self.writer.write((json.dumps(message, default=str) + "\n").encode())
        await self.writer.drain()

    async def _read_loop(self) -> None:
        while True:
            line = await self.reader.readline()
            if not line:
                for waiting in self._pending.values():
                    if not waiting.done():
                        waiting.set_exception(RpcError("peer closed"))
                return
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "method" in msg:
                task = asyncio.create_task(self._serve(msg))
                self._serving.add(task)
                task.add_done_callback(self._serving.discard)
            else:
                fut = self._pending.get(int(msg.get("id", -1)))
                if fut is not None and not fut.done():
                    if "error" in msg:
                        fut.set_exception(RpcError(str(msg["error"])))
                    else:
                        fut.set_result(msg.get("result"))

    async def _serve(self, msg: dict[str, Any]) -> None:
        try:
            result = await self.handler(str(msg["method"]), dict(msg.get("params") or {}))
            await self._send({"id": msg["id"], "result": result})
        except Exception as exc:
            await self._send({"id": msg["id"], "error": f"{type(exc).__name__}: {exc}"})

    async def wait_closed(self) -> None:
        if self._task:
            await self._task
