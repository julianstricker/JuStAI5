"""Voice control tools: privacy mode, listening pause, image analysis."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from justai_sdk.ports.devices import Capability
from justai_sdk.tools import InvocationOrigin, ToolContext

from justai.endpoints.service import DeviceRole, EndpointConfig
from justai.tools.builtin import control


class Privacy:
    def __init__(self) -> None:
        self.state = False

    async def set(self, enabled: bool) -> None:
        self.state = enabled


def runtime(device_id: str, name: str, room: str, caps: set[str]) -> Any:
    priv = Privacy()
    handle = SimpleNamespace(privacy=lambda: priv)
    return SimpleNamespace(device_id=device_id, name=name, room_id=room, capabilities=caps,
                           handle=handle, priv=priv)


class Registry:
    def __init__(self) -> None:
        self.tools: dict[str, Any] = {}

    def register(self, definition: Any, handler: Any) -> None:
        self.tools[definition.name] = (definition, handler)


def container() -> Any:
    rts = [runtime("cam1", "Living room camera", "living", {Capability.CAMERA_PRIVACY_MODE, Capability.VIDEO_INPUT}),
           runtime("cam2", "Kitchen camera", "kitchen", {Capability.CAMERA_PRIVACY_MODE, Capability.VIDEO_INPUT})]
    audit: list[tuple[str, dict[str, Any]]] = []
    endpoint = SimpleNamespace(id="ep1", name="Living", room_id="living", config=EndpointConfig(),
                               primary=lambda role: "cam1" if role == DeviceRole.MIC else None)
    updates: list[Any] = []

    class Endpoints:
        async def list(self) -> list[Any]:
            return [endpoint]

        async def update(self, endpoint_id: str, patch: Any) -> None:
            updates.append(patch)
            endpoint.config = patch.config

    class Audit:
        async def record(self, actor: str, action: str, target: str, **kw: Any) -> None:
            audit.append((action, kw))

    async def nothing() -> None:
        return None

    return SimpleNamespace(
        tools=Registry(), devices=SimpleNamespace(runtimes=lambda: rts), audit=Audit(),
        endpoints=Endpoints(), refresh_topology=nothing, extensions={}, rts=rts, updates=updates,
        audit_log=audit, endpoint=endpoint,
        rooms=SimpleNamespace(find=lambda name: asyncio.sleep(0, SimpleNamespace(id=name))),
        settings_store=SimpleNamespace(get=lambda *a: asyncio.sleep(0, {})))


def ctx(room: str = "living") -> ToolContext:
    return ToolContext(call_id="t", origin=InvocationOrigin.CONVERSATION, room_id=room, session_id="s")


def call(c: Any, name: str, args: dict[str, Any], context: ToolContext) -> Any:
    definition, handler = c.tools.tools[name]
    return asyncio.run(handler(definition.parameters.model_validate(args), context))


def test_privacy_mode_switches_the_camera_of_the_room_only() -> None:
    c = container()
    control.register(c)
    result = call(c, "devices.privacy_mode", {"enabled": True}, ctx("living"))
    assert result.ok and c.rts[0].priv.state is True and c.rts[1].priv.state is False
    assert c.audit_log[-1][0] == "device.privacy_mode"


def test_privacy_mode_everywhere_and_by_name() -> None:
    c = container()
    control.register(c)
    assert call(c, "devices.privacy_mode", {"enabled": True, "everywhere": True}, ctx()).ok
    assert all(r.priv.state for r in c.rts)
    assert call(c, "devices.privacy_mode", {"enabled": False, "device": "kitchen"}, ctx()).ok
    assert c.rts[1].priv.state is False and c.rts[0].priv.state is True


def test_listening_pause_disables_the_wakeword_and_enabling_restores_it() -> None:
    c = container()
    control.register(c)
    result = call(c, "audio.listening", {"enabled": False, "minutes": 30}, ctx())
    assert result.ok and c.endpoint.config.wakeword.enabled is False
    assert "until" in result.data
    assert call(c, "audio.listening", {"enabled": True}, ctx()).ok
    assert c.endpoint.config.wakeword.enabled is True


def test_unknown_device_is_a_clear_failure() -> None:
    c = container()
    control.register(c)
    result = call(c, "devices.privacy_mode", {"enabled": True, "device": "garage"}, ctx())
    assert not result.ok and "garage" in (result.message or "")
