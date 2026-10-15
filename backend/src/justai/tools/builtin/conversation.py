"""Conversation control tools: confirmations, ending, announcements."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from justai_sdk.permissions import Permission
from justai_sdk.tools import NoParams, SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.common.errors import RoutingDenied
from justai.common.tasks import spawn

if TYPE_CHECKING:
    from justai.container import Container


class Token(BaseModel):
    token: str = Field(description="Bestätigungs-Token aus der vorherigen Tool-Antwort")


class Announce(BaseModel):
    room: str = Field(description="Zielraum (Name oder ID)")
    text: str = Field(max_length=500, description="Was im Zielraum gesagt werden soll")


def register(c: Container) -> None:
    reg = c.tools

    async def confirm(params: Token, ctx: ToolContext) -> ToolResult:
        # Sessions route this tool to ToolExecutor.confirm (requires a new user turn).
        return await c.executor.confirm(params.token, ctx)

    reg.register(ToolDefinition(
        name="assistant.confirm_action",
        description="Führt eine Aktion aus, die eine Bestätigung brauchte - NUR nachdem der Benutzer "
                    "in seiner letzten Äußerung ausdrücklich zugestimmt hat.",
        parameters=Token, category="assistant", side_effect=SideEffect.WRITE), confirm)

    async def cancel(params: Token, ctx: ToolContext) -> ToolResult:
        c.confirmations.cancel(params.token)
        return ToolResult.success(message="Aktion verworfen")

    reg.register(ToolDefinition(
        name="assistant.cancel_action", description="Verwirft eine wartende, zu bestätigende Aktion.",
        parameters=Token, category="assistant"), cancel)

    async def end(_: NoParams, ctx: ToolContext) -> ToolResult:
        session = c.conversations.get(ctx.session_id or "")
        if session is None:
            return ToolResult.failure("no_session", "Kein aktives Gespräch")

        async def later() -> None:
            await asyncio.sleep(4)  # let the goodbye be spoken first
            await session.end("assistant")

        spawn(later())
        return ToolResult.success(message="Gespräch wird nach der Antwort beendet")

    reg.register(ToolDefinition(
        name="conversation.end",
        description="Beendet das Gespräch, wenn der Benutzer sich verabschiedet oder nichts mehr will.",
        parameters=NoParams, category="conversation"), end)

    async def announce(params: Announce, ctx: ToolContext) -> ToolResult:
        speech = c.extensions["speech"]
        room = await c.rooms.find(params.room)
        if room is None:
            return ToolResult.failure("unknown_room", f"Raum '{params.room}' unbekannt")
        try:
            decision = speech.resolve(target_room_id=room.id, origin_endpoint_id=ctx.endpoint_id,
                                      origin_room_id=ctx.room_id, explicit_cross_room=True,
                                      permissions=ctx.permissions)
        except RoutingDenied as exc:
            return ToolResult.failure("routing_denied", exc.message)
        await c.audit.record("assistant", "output.announce", room.id, text=params.text[:200],
                             session=ctx.session_id)
        spawn(speech.say(params.text, decision, language=ctx.language))
        return ToolResult.success({"room": room.name},
                                  message=f"Durchsage wird in {room.name} abgespielt")

    reg.register(ToolDefinition(
        name="conversation.announce",
        description="Ausdrückliche Durchsage in einem ANDEREN Raum (z. B. 'Sag in der Küche Bescheid, "
                    "dass das Essen fertig ist'). Für normale Antworten nicht verwenden.",
        parameters=Announce, category="conversation", side_effect=SideEffect.PHYSICAL,
        permissions=[Permission.SPEAKER_WRITE, Permission.OUTPUT_CROSS_ROOM]), announce)
