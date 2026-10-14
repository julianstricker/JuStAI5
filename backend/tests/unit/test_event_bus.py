import asyncio

import pytest
from justai_sdk.events import Durability, Event

from justai.common.errors import ValidationFailed
from justai.events import EventBus, build_core_catalog


class FakeStore:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def append(self, event: Event) -> None:
        self.events.append(event)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
async def bus(store: FakeStore):
    b = EventBus(build_core_catalog(), store, max_hops=3)
    yield b
    await b.close()


async def test_pattern_subscription_and_delivery(bus: EventBus) -> None:
    got: list[str] = []

    async def handler(e: Event) -> None:
        got.append(e.type)

    bus.subscribe("vision.*", handler)
    await bus.publish(Event(type="vision.motion.started"))
    await bus.publish(Event(type="audio.wakeword.rejected"))
    await bus.drain()
    assert got == ["vision.motion.started"]


async def test_failing_subscriber_does_not_affect_others(bus: EventBus) -> None:
    got: list[str] = []

    async def bad(e: Event) -> None:
        raise RuntimeError("boom")

    async def good(e: Event) -> None:
        got.append(e.id)

    bus.subscribe("*", bad, name="bad")
    bus.subscribe("*", good, name="good")
    for _ in range(3):
        await bus.publish(Event(type="manual.test"))
    await bus.drain()
    assert len(got) == 3
    stats = {s["name"]: s for s in bus.subscriber_stats()}
    assert stats["bad"]["failed"] == 3


async def test_deduplication_by_id_and_key(bus: EventBus) -> None:
    e = Event(type="manual.test")
    assert await bus.publish(e) is True
    assert await bus.publish(e) is False
    assert await bus.publish(Event(type="manual.test", dedup_key="x")) is True
    assert await bus.publish(Event(type="manual.test", dedup_key="x")) is False
    assert bus.stats.duplicates == 2


async def test_loop_protection_stops_deep_chains(bus: EventBus, store: FakeStore) -> None:
    root = Event(type="manual.test")
    chain = root
    for _ in range(4):
        chain = chain.caused("manual.test")
    assert chain.hop == 4
    assert await bus.publish(chain) is False
    assert bus.stats.loops_stopped == 1
    assert any(e.type == "system.event_loop_detected" for e in store.events)


async def test_durable_events_are_persisted(bus: EventBus, store: FakeStore) -> None:
    await bus.publish(Event(type="conversation.session.started"))
    await bus.publish(Event(type="vision.motion.started"))
    assert [e.type for e in store.events] == ["conversation.session.started"]
    assert store.events[0].durability == Durability.DURABLE


async def test_payload_validation(bus: EventBus) -> None:
    with pytest.raises(ValidationFailed):
        await bus.publish(Event(type="vision.person.recognized", payload={"camera_id": "x"}))


async def test_slow_subscriber_does_not_block_publisher(store: FakeStore) -> None:
    bus = EventBus(build_core_catalog(), store, subscriber_queue_size=2)
    release = asyncio.Event()

    async def slow(e: Event) -> None:
        await release.wait()

    bus.subscribe("*", slow, name="slow")
    for _ in range(10):
        await asyncio.wait_for(bus.publish(Event(type="vision.motion.started")), 0.5)
    stats = bus.subscriber_stats()[0]
    assert stats["dropped"] >= 7
    release.set()
    await bus.close()
