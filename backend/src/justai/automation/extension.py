"""Automation feature: engine lifecycle and assistant tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from justai_sdk.permissions import Permission
from justai_sdk.tools import NoParams, SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.automation.engine import AutomationEngine, AutomationService

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry


class CreateParams(BaseModel):
    name: str = Field(description="Kurzer Name, z. B. 'Julian begrüßen'")
    description: str = Field("", description="Was die Regel tut (in Worten)")
    trigger: dict[str, Any] = Field(description=(
        "Auslöser. Ereignis: {\"type\":\"event\",\"event\":\"vision.person.recognized\","
        "\"match\":{\"person_id\":\"self\"}} - 'self' steht für die sprechende Person. "
        "Weitere Ereignisse: vision.object.appeared (match label), vision.watch.triggered, "
        "vision.state.changed (match name/state), display.interaction. Zeit: {\"type\":\"cron\","
        "\"cron\":\"0 7 * * 1-5\"}, {\"type\":\"at\",\"at\":\"2026-10-15T07:30:00\"}, "
        "{\"type\":\"interval\",\"seconds\":3600}"))
    conditions: list[dict[str, Any]] = Field(default_factory=list, description=(
        "Optional: {\"type\":\"time_window\",\"start\":\"07:00\",\"end\":\"22:00\"}, "
        "{\"type\":\"no_active_conversation\",\"room\":\"trigger\"}, "
        "{\"type\":\"visual_state\",\"detector\":\"Garagentor\",\"state\":\"offen\"}"))
    actions: list[dict[str, Any]] = Field(description=(
        "Aktionen: {\"type\":\"assistant.invoke\",\"instruction\":\"Begrüße Julian mit Namen\","
        "\"room\":\"trigger\"} | {\"type\":\"speak\",\"text\":\"...\",\"room\":\"here\"} | "
        "{\"type\":\"display.show\",\"document\":{...},\"room\":\"trigger\"} | "
        "{\"type\":\"tool\",\"name\":\"...\",\"args\":{}}. room: 'trigger' = Raum des Auslösers, "
        "'here' = aktueller Raum."))
    once: bool = Field(False, description="Nur einmal ausführen (z. B. 'das nächste Mal')")
    cooldown_s: float = Field(0, description="Mindestabstand zwischen Ausführungen in Sekunden")


class IdParams(BaseModel):
    automation_id: str


class EnableParams(IdParams):
    enabled: bool


def _substitute(value: Any, ctx: ToolContext) -> Any:
    if isinstance(value, dict):
        return {k: _substitute(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, ctx) for v in value]
    if value == "self":
        if not ctx.person_id:
            raise LookupError("speaker unknown")
        return ctx.person_id
    if value == "here":
        if not ctx.room_id:
            raise LookupError("room unknown")
        return ctx.room_id
    return value


class AutomationExtension:
    def __init__(self, c: Container) -> None:
        self.c = c
        self.service = AutomationService(c.db)
        self.engine = AutomationEngine(c, self.service, c.bus, c.jobs)

    async def start(self) -> None:
        await self.engine.start()

    async def stop(self) -> None:
        await self.engine.stop()

    def register_tools(self, reg: ToolRegistry) -> None:
        svc, engine = self.service, self.engine

        async def create(p: CreateParams, ctx: ToolContext) -> ToolResult:
            try:
                definition = _substitute({
                    "trigger": p.trigger, "conditions": p.conditions, "actions": p.actions,
                    "options": {"once": p.once, "cooldown_s": p.cooldown_s}}, ctx)
            except LookupError as exc:
                if str(exc) == "speaker unknown":
                    return ToolResult.failure("speaker_unknown", "Ich weiß nicht, wer spricht. Bitte die "
                                              "Person, sich vorzustellen (identity.introduce) bzw. ihr Gesicht "
                                              "registrieren zu lassen, damit ich sie erkenne.")
                return ToolResult.failure("room_unknown", "Kein aktueller Raum bekannt")
            auto = await svc.create_from_definition(
                name=p.name, description=p.description, definition=definition, created_by="assistant",
                owner_person_id=ctx.person_id, origin={"session_id": ctx.session_id})
            await engine.reload()
            await self.c.audit.record("assistant", "automation.create", auto.id, name=p.name,
                                      session=ctx.session_id)
            return ToolResult.success({"automation_id": auto.id}, message=f"Automation '{p.name}' angelegt")

        reg.register(ToolDefinition(
            name="automation.create",
            description="Legt eine dauerhafte Regel an (Trigger -> Bedingungen -> Aktionen), z. B. 'Wenn du "
                        "mich das nächste Mal siehst, begrüße mich mit Namen'.",
            parameters=CreateParams, category="automation", side_effect=SideEffect.WRITE,
            permissions=[Permission.AUTOMATION_MANAGE]), create)

        async def list_(_: NoParams, ctx: ToolContext) -> ToolResult:
            autos = await svc.list()
            return ToolResult.success([{"id": a.id, "name": a.name, "enabled": a.enabled,
                                        "description": a.description} for a in autos])

        reg.register(ToolDefinition(
            name="automation.list", description="Listet die Automationen.", parameters=NoParams,
            category="automation", permissions=[Permission.AUTOMATION_MANAGE]), list_)

        async def enable(p: EnableParams, ctx: ToolContext) -> ToolResult:
            await svc.update(p.automation_id, enabled=p.enabled)
            await engine.reload()
            return ToolResult.success(message="aktiviert" if p.enabled else "deaktiviert")

        reg.register(ToolDefinition(
            name="automation.set_enabled", description="Aktiviert oder deaktiviert eine Automation.",
            parameters=EnableParams, category="automation", side_effect=SideEffect.WRITE,
            permissions=[Permission.AUTOMATION_MANAGE]), enable)

        async def delete(p: IdParams, ctx: ToolContext) -> ToolResult:
            await svc.delete(p.automation_id)
            await engine.reload()
            return ToolResult.success(message="gelöscht")

        reg.register(ToolDefinition(
            name="automation.delete", description="Löscht eine Automation (nach Bestätigung).",
            parameters=IdParams, category="automation", side_effect=SideEffect.WRITE,
            requires_confirmation=True, permissions=[Permission.AUTOMATION_MANAGE]), delete)


def describe_schema() -> dict[str, Any]:
    from justai.automation.model import definition_schema

    return json.loads(json.dumps(definition_schema()))
