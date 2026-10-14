"""Core operations offered to plugins through ``ctx.services`` (permission-checked
in the plugin context before they reach this backend)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from justai_sdk.ports.ai import ChatMessage, Role

from justai.ai.config import ModelRole
from justai.common.errors import Unavailable

if TYPE_CHECKING:
    from justai.container import Container


class CoreServicesBackend:
    def __init__(self, container: Container) -> None:
        self.c = container

    async def list_devices(self) -> list[dict[str, Any]]:
        return [{"id": d.id, "name": d.name, "room_id": d.room_id, "status": d.status,
                 "capabilities": d.capabilities} for d in await self.c.device_records.list()]

    async def list_rooms(self) -> list[dict[str, Any]]:
        return [{"id": r.id, "name": r.name} for r in await self.c.rooms.list()]

    async def snapshot(self, device_id: str) -> bytes:
        return await self.c.devices.snapshot(device_id)

    async def memory_search(self, query: str, person_id: str | None, limit: int) -> list[dict[str, Any]]:
        if self.c.memory is None:
            return []
        hits = await self.c.memory.search(query, person_id=person_id, limit=limit,
                                          scopes=("shared", "system", "room"))
        return [h.model_dump(mode="json") for h in hits]

    async def say(self, room_id: str, text: str, plugin_id: str) -> None:
        speech = self.c.extensions.get("speech")
        if speech is None:
            raise Unavailable("speech output not available")
        decision = speech.resolve(target_room_id=room_id, system=True)
        await self.c.audit.record(f"plugin:{plugin_id}", "output.say", room_id, text=text[:200])
        await speech.say(text, decision)

    async def show(self, room_id: str, document: dict[str, Any], plugin_id: str) -> str:
        display = self.c.extensions.get("display")
        if display is None:
            raise Unavailable("displays not available")
        presentation = await display.present(document, target_room_id=room_id, system=True,
                                             source=f"plugin:{plugin_id}")
        return str(presentation.id)

    async def complete(self, prompt: str, role: str) -> str:
        result = await self.c.ai.chat(ModelRole(role), [ChatMessage(role=Role.USER, content=prompt)])
        return result.text
