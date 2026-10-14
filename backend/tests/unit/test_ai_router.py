from collections.abc import AsyncIterator

import pytest
from justai_sdk.events import Event
from justai_sdk.ports.ai import ChatEvent, ChatEventKind, ChatMessage, ChatRequest, Locality, Role

from justai.ai.config import AISettings, Locality as RoleLocality, ModelRef, ModelRole, RoleConfig
from justai.ai.router import AIRouter, DataFlags
from justai.ai.usage import UsageTracker
from justai.common.errors import PolicyViolation
from justai.events import EventBus, build_core_catalog
from justai.plugins.providers import ProviderRegistry


class FakeLLM:
    def __init__(self, pid: str, locality: Locality, fail: bool = False) -> None:
        self.provider_id = pid
        self.locality = locality
        self.fail = fail
        self.calls = 0

    async def chat(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        self.calls += 1
        if self.fail:
            raise ConnectionError("down")
        yield ChatEvent(kind=ChatEventKind.TEXT, text=f"answer from {self.provider_id}")
        yield ChatEvent(kind=ChatEventKind.DONE)

    async def list_models(self):  # type: ignore[no-untyped-def]
        return []


MSG = [ChatMessage(role=Role.USER, content="hi")]


async def make(settings: AISettings, *providers: FakeLLM):  # type: ignore[no-untyped-def]
    reg = ProviderRegistry()
    for p in providers:
        reg.register("llm", p, "test")
    bus = EventBus(build_core_catalog())
    events: list[Event] = []

    async def collect(e: Event) -> None:
        events.append(e)

    bus.subscribe("ai.*", collect)
    audits: list[str] = []

    async def audit(action: str, detail: dict) -> None:  # type: ignore[type-arg]
        audits.append(action)

    async def load() -> AISettings:
        return settings

    return AIRouter(reg, load, bus, UsageTracker(None), audit), bus, events, audits


def chain(*names: str, locality: RoleLocality = RoleLocality.ANY) -> AISettings:
    return AISettings(roles={ModelRole.CONVERSATION: RoleConfig(
        chain=[ModelRef(provider=n, model="m") for n in names], locality=locality)})


async def test_primary_used() -> None:
    local = FakeLLM("local", Locality.LOCAL)
    router, bus, _, _ = await make(chain("local"), local)
    r = await router.chat(ModelRole.CONVERSATION, MSG)
    assert r.text == "answer from local" and r.provider == "local"
    await bus.close()


async def test_fallback_is_announced_and_audited_when_going_to_cloud() -> None:
    local = FakeLLM("local", Locality.LOCAL, fail=True)
    cloud = FakeLLM("cloud", Locality.CLOUD)
    router, bus, events, audits = await make(chain("local", "cloud", locality=RoleLocality.PREFER_LOCAL),
                                              local, cloud)
    r = await router.chat(ModelRole.CONVERSATION, MSG)
    assert r.provider == "cloud"
    await bus.drain()
    assert events and events[0].payload["local_to_cloud"] is True
    assert audits == ["ai.cloud_fallback"]
    await bus.close()


async def test_local_only_never_falls_back_to_cloud() -> None:
    local = FakeLLM("local", Locality.LOCAL, fail=True)
    cloud = FakeLLM("cloud", Locality.CLOUD)
    router, bus, _, _ = await make(chain("local", "cloud", locality=RoleLocality.LOCAL_ONLY), local, cloud)
    with pytest.raises(Exception):  # noqa: B017
        await router.chat(ModelRole.CONVERSATION, MSG)
    assert cloud.calls == 0
    await bus.close()


async def test_privacy_blocks_images_to_cloud() -> None:
    cloud = FakeLLM("cloud", Locality.CLOUD)
    s = chain("cloud")
    s.privacy.camera_images_to_cloud = False
    router, bus, _, _ = await make(s, cloud)
    with pytest.raises(PolicyViolation):
        await router.chat(ModelRole.CONVERSATION, MSG, flags=DataFlags(images=True))
    assert cloud.calls == 0
    assert (await router.chat(ModelRole.CONVERSATION, MSG)).provider == "cloud"
    await bus.close()


async def test_role_borrows_chain_but_keeps_its_locality() -> None:
    cloud = FakeLLM("cloud", Locality.CLOUD)
    s = chain("cloud")
    s.roles[ModelRole.MEMORY] = RoleConfig(chain=[], locality=RoleLocality.LOCAL_ONLY)
    router, bus, _, _ = await make(s, cloud)
    usable, skipped = await router.candidates(ModelRole.MEMORY)
    assert not usable and "local" in skipped[0]
    usable, _ = await router.candidates(ModelRole.BACKGROUND)
    assert [c.ref.provider for c in usable] == ["cloud"]
    await bus.close()


async def test_cost_limit_blocks_cloud() -> None:
    cloud = FakeLLM("cloud", Locality.CLOUD)
    s = chain("cloud")
    s.cost_limits.daily_usd = 1.0
    router, bus, _, _ = await make(s, cloud)
    router.usage.record(provider="cloud", model="m", role="x", ok=True, cost_usd=1.5)
    usable, skipped = await router.candidates(ModelRole.CONVERSATION)
    assert not usable and "cost" in skipped[0]
    await bus.close()
