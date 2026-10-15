"""In-process event bus.

* Each subscriber has its own bounded queue and worker task, so a slow or failing
  subscriber never blocks others (error isolation).
* Durable events are handed to the :class:`EventStore` before delivery.
* Duplicate events (same id, or same ``dedup_key`` within a TTL) are dropped.
* Events whose ``hop`` count exceeds ``max_hops`` are stopped (loop protection).

The bus is an implementation of a port: the rest of the system depends only on
``publish``/``subscribe``, so it can later be swapped for NATS/Redis if components
are moved into separate processes.
"""

from __future__ import annotations

import asyncio
import contextlib
import fnmatch
import itertools
import time
from collections import OrderedDict, deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

from justai_sdk.events import Durability, Event, EventPriority

from justai.events.catalog import EventCatalog
from justai.logging import get_logger

log = get_logger(__name__)

Handler = Callable[[Event], Awaitable[None]]


class EventPersistence(Protocol):
    async def append(self, event: Event) -> None: ...


@dataclass
class _Subscriber:
    name: str
    pattern: str
    handler: Handler
    queue: asyncio.Queue[Event]
    task: asyncio.Task[None] | None = None
    delivered: int = 0
    failed: int = 0
    dropped: int = 0
    last_error: str | None = None

    def matches(self, type: str) -> bool:
        return self.pattern == "*" or fnmatch.fnmatchcase(type, self.pattern)


@dataclass
class BusStats:
    published: int = 0
    duplicates: int = 0
    loops_stopped: int = 0
    persisted: int = 0
    by_type: dict[str, int] = field(default_factory=dict)


class _DedupCache:
    def __init__(self, ttl_s: float, max_items: int = 10_000) -> None:
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._items: OrderedDict[str, float] = OrderedDict()

    def seen(self, key: str) -> bool:
        now = time.monotonic()
        while self._items:
            _, ts = next(iter(self._items.items()))
            if now - ts > self.ttl_s or len(self._items) > self.max_items:
                self._items.popitem(last=False)
            else:
                break
        if key in self._items:
            return True
        self._items[key] = now
        return False


class EventBus:
    def __init__(
        self,
        catalog: EventCatalog,
        persistence: EventPersistence | None = None,
        *,
        max_hops: int = 8,
        subscriber_queue_size: int = 1000,
        dedup_ttl_s: float = 30.0,
        recent_size: int = 500,
    ) -> None:
        self.catalog = catalog
        self.persistence = persistence
        self.max_hops = max_hops
        self._queue_size = subscriber_queue_size
        self._subscribers: dict[int, _Subscriber] = {}
        self._ids = itertools.count(1)
        self._dedup = _DedupCache(dedup_ttl_s)
        self._recent: deque[Event] = deque(maxlen=recent_size)
        self.stats = BusStats()
        self._running = True

    # ----------------------------------------------------------------- subscribe
    def subscribe(self, pattern: str, handler: Handler, *, name: str = "") -> Callable[[], None]:
        sub_id = next(self._ids)
        sub = _Subscriber(
            name=name or getattr(handler, "__qualname__", f"sub{sub_id}"),
            pattern=pattern,
            handler=handler,
            queue=asyncio.Queue(self._queue_size),
        )
        sub.task = asyncio.create_task(self._worker(sub), name=f"event-sub:{sub.name}")
        self._subscribers[sub_id] = sub

        def unsubscribe() -> None:
            removed = self._subscribers.pop(sub_id, None)
            if removed and removed.task:
                removed.task.cancel()

        return unsubscribe

    async def _worker(self, sub: _Subscriber) -> None:
        while True:
            event = await sub.queue.get()
            try:
                await sub.handler(event)
                sub.delivered += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                sub.failed += 1
                sub.last_error = f"{type(exc).__name__}: {exc}"
                log.warning("event handler failed", subscriber=sub.name, event_type=event.type,
                            error=str(exc), exc_info=True)
            finally:
                sub.queue.task_done()

    # ------------------------------------------------------------------- publish
    async def publish(self, event: Event) -> bool:
        """Publish an event. Returns False if it was dropped (duplicate or loop)."""
        if not self._running:
            return False
        if self._dedup.seen(f"id:{event.id}") or (
            event.dedup_key and self._dedup.seen(f"key:{event.type}:{event.dedup_key}")
        ):
            self.stats.duplicates += 1
            return False
        if event.hop > self.max_hops:
            self.stats.loops_stopped += 1
            log.warning("event loop stopped", event_type=event.type, hop=event.hop,
                        correlation_id=event.correlation_id)
            if event.type != "system.event_loop_detected":
                guard = Event(
                    type="system.event_loop_detected",
                    payload={"stopped_type": event.type, "hop": event.hop},
                    correlation_id=event.correlation_id,
                    priority=EventPriority.HIGH,
                )
                await self.publish(guard)
            return False

        self.catalog.validate_payload(event.type, event.payload)
        if event.durability is None:
            event = event.model_copy(update={"durability": self.catalog.default_durability(event.type)})
        spec = self.catalog.get(event.type)
        if spec and event.priority == EventPriority.NORMAL and spec.priority != EventPriority.NORMAL:
            event = event.model_copy(update={"priority": spec.priority})

        self.stats.published += 1
        self.stats.by_type[event.type] = self.stats.by_type.get(event.type, 0) + 1
        self._recent.append(event)

        if event.durability == Durability.DURABLE and self.persistence is not None:
            try:
                await self.persistence.append(event)
                self.stats.persisted += 1
            except Exception as exc:  # persistence must not stop delivery
                log.error("event persistence failed", event_type=event.type, error=str(exc))

        for sub in list(self._subscribers.values()):
            if not sub.matches(event.type):
                continue
            await self._enqueue(sub, event)
        return True

    async def _enqueue(self, sub: _Subscriber, event: Event) -> None:
        try:
            sub.queue.put_nowait(event)
            return
        except asyncio.QueueFull:
            pass
        if event.durability == Durability.DURABLE or event.priority >= EventPriority.HIGH:
            try:
                await asyncio.wait_for(sub.queue.put(event), timeout=2.0)
                return
            except TimeoutError:
                pass
        sub.dropped += 1
        log.warning("subscriber queue full, event dropped", subscriber=sub.name,
                    event_type=event.type)

    # ------------------------------------------------------------------ utilities
    def recent(self, limit: int = 100, pattern: str = "*") -> list[Event]:
        items = [e for e in self._recent if pattern == "*" or fnmatch.fnmatchcase(e.type, pattern)]
        return items[-limit:]

    def subscriber_stats(self) -> list[dict[str, object]]:
        return [
            {
                "name": s.name,
                "pattern": s.pattern,
                "queued": s.queue.qsize(),
                "delivered": s.delivered,
                "failed": s.failed,
                "dropped": s.dropped,
                "last_error": s.last_error,
            }
            for s in self._subscribers.values()
        ]

    async def drain(self, timeout_s: float = 5.0) -> None:
        """Wait until all queued events were handled (used by tests and shutdown)."""
        deadline = time.monotonic() + timeout_s
        for sub in list(self._subscribers.values()):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(sub.queue.join(), timeout=remaining)

    async def close(self) -> None:
        self._running = False
        await self.drain(2.0)
        for sub in list(self._subscribers.values()):
            if sub.task:
                sub.task.cancel()
        self._subscribers.clear()
