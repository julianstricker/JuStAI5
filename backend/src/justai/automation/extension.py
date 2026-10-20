"""Automation feature: engine lifecycle and assistant tools."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from justai_sdk.permissions import Permission
from justai_sdk.tools import NoParams, SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from justai.automation.engine import AutomationEngine, AutomationService
from justai.common.errors import ValidationFailed
from justai.db.models import Person

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry


class CreateParams(BaseModel):
    name: str = Field(description="Short name, e.g. 'Greet Julian'")
    description: str = Field("", description="What the rule does (in words)")
    trigger: dict[str, Any] = Field(description=(
        "Trigger. Event: {\"type\":\"event\",\"event\":\"vision.person.recognized\","
        "\"match\":{\"person_id\":\"self\"}} - 'self' is the speaking person. "
        "Other events: vision.object.appeared (match label), vision.watch.triggered, "
        "vision.state.changed (match name/state), display.interaction, events of plugins "
        "plugin.<id>.<name> (list them with events.types). For vision.person.recognized "
        "this applies automatically: only after at least 10 minutes of absence (condition payload "
        "away_s >= 600); set other gaps yourself, e.g. 'when I come home' away_s >= 3600, "
        "'every time' away_s >= 0. Time (local time): {\"type\":\"cron\","
        "\"cron\":\"0 7 * * 1-5\"}, one-time reminder {\"type\":\"at\",\"at\":\"2026-10-15T07:30:00\"}, "
        "{\"type\":\"interval\",\"seconds\":3600}"))
    conditions: list[dict[str, Any]] = Field(default_factory=list, description=(
        "Optional: {\"type\":\"time_window\",\"start\":\"07:00\",\"end\":\"22:00\"}, "
        "{\"type\":\"no_active_conversation\",\"room\":\"trigger\"}, "
        "{\"type\":\"visual_state\",\"detector\":\"garage door\",\"state\":\"open\"}"))
    actions: list[dict[str, Any]] = Field(description=(
        "Actions: {\"type\":\"assistant.invoke\",\"instruction\":\"Greet Julian by name\","
        "\"room\":\"trigger\"} | {\"type\":\"speak\",\"text\":\"...\",\"room\":\"here\"} | "
        "{\"type\":\"display.show\",\"document\":{...},\"room\":\"trigger\"} | "
        "{\"type\":\"tool\",\"name\":\"...\",\"args\":{}}. room: 'trigger' = room of the trigger, "
        "'here' = current room. A speak text is spoken as written: write it in the user's language."))
    once: bool = Field(False, description="Run only once (e.g. 'the next time')")
    cooldown_s: float = Field(0, description="Minimum time between runs in seconds")
    not_before: str | None = Field(None, description=(
        "Earliest time (local time, ISO); the trigger is ignored before it, e.g. 'when you see me "
        "from tomorrow 9 am' -> '2026-10-17T09:00:00'"))
    expires_at: str | None = Field(None, description="Disable from this time on (local time, ISO)")


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


_TRIGGER_KEYS = (("event", "event"), ("cron", "cron"), ("at", "at"), ("seconds", "interval"))
_ACTION_KEYS = (("instruction", "assistant.invoke"), ("document", "display.show"), ("text", "speak"),
                ("seconds", "wait"), ("event", "event.emit"), ("name", "tool"))
_CONDITION_KEYS = (("start", "time_window"), ("path", "payload"), ("detector", "visual_state"))


def _with_type(item: Any, keys: tuple[tuple[str, str], ...]) -> Any:
    """Models often omit the discriminator; infer it from the fields that are present."""
    if isinstance(item, dict) and "type" not in item:
        for key, type_ in keys:
            if key in item:
                return {"type": type_, **item}
    return item


def normalize_definition(definition: dict[str, Any]) -> dict[str, Any]:
    return {
        **definition,
        "trigger": _with_type(definition.get("trigger"), _TRIGGER_KEYS),
        "conditions": [_with_type(c, _CONDITION_KEYS) for c in definition.get("conditions") or []],
        "actions": [_with_type(a, _ACTION_KEYS) for a in definition.get("actions") or []],
    }


# "Wenn du mich das nächste Mal siehst": the person must have been away, otherwise the rule
# fires while they are still sitting in front of the camera (tracks are re-identified
# whenever a still person is lost between detector runs).
DEFAULT_AWAY_S = 600


def add_default_absence(definition: dict[str, Any]) -> dict[str, Any]:
    trigger = definition.get("trigger") or {}
    if not isinstance(trigger, dict) or trigger.get("event") != "vision.person.recognized":
        return definition
    conditions = list(definition.get("conditions") or [])
    if any(isinstance(c, dict) and c.get("path") == "away_s" for c in conditions):
        return definition
    conditions.append({"type": "payload", "path": "away_s", "op": ">=", "value": DEFAULT_AWAY_S})
    return {**definition, "conditions": conditions}


def describe_errors(exc: ValidationFailed) -> str:
    errors = exc.details.get("errors") or []
    parts = [f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in errors[:6]]
    return "; ".join(parts) or exc.message


class AutomationExtension:
    def __init__(self, c: Container) -> None:
        self.c = c
        self.service = AutomationService(c.db)
        self.engine = AutomationEngine(c, self.service, c.bus, c.jobs)

    async def start(self) -> None:
        await self.engine.start()

    async def stop(self) -> None:
        await self.engine.stop()

    async def _resolve_people(self, definition: dict[str, Any]) -> str | None:
        """Replace person names in event matches by person ids; returns an unknown name."""
        trigger = definition.get("trigger")
        match = trigger.get("match") if isinstance(trigger, dict) else None
        if not isinstance(match, dict):
            return None
        value = match.get("person_id")
        if not isinstance(value, str) or value.startswith("person-"):
            return None
        async with self.c.db.session() as s:
            person_id = await s.scalar(select(Person.id).where(
                func.lower(Person.name) == value.strip().lower(), Person.merged_into.is_(None)))
        if person_id is None:
            return value
        match["person_id"] = person_id
        return None

    def register_tools(self, reg: ToolRegistry) -> None:
        svc, engine = self.service, self.engine

        async def create(p: CreateParams, ctx: ToolContext) -> ToolResult:
            try:
                definition = _substitute({
                    "trigger": p.trigger, "conditions": p.conditions, "actions": p.actions,
                    "options": {"once": p.once, "cooldown_s": p.cooldown_s,
                                "not_before": p.not_before or None, "expires_at": p.expires_at or None}}, ctx)
            except LookupError as exc:
                if str(exc) == "speaker unknown":
                    return ToolResult.failure("speaker_unknown", "I do not know who is speaking. Ask the "
                                              "person to introduce themselves (identity.introduce) or to have "
                                              "their face registered so I recognise them.")
                return ToolResult.failure("room_unknown", "No current room known")
            definition = add_default_absence(normalize_definition(definition))
            unknown = await self._resolve_people(definition)
            if unknown:
                return ToolResult.failure("person_unknown", f"Unknown person '{unknown}'. Look up the "
                                          "right person_id with identity.list_people.")
            try:
                auto = await svc.create_from_definition(
                    name=p.name, description=p.description, definition=definition, created_by="assistant",
                    owner_person_id=ctx.person_id, origin={"session_id": ctx.session_id})
            except ValidationFailed as exc:
                return ToolResult.failure("invalid_automation", f"Invalid automation ({describe_errors(exc)}). "
                                          "Correct the definition and try again.")
            await engine.reload()
            await self.c.audit.record("assistant", "automation.create", auto.id, name=p.name,
                                      session=ctx.session_id)
            return ToolResult.success({"automation_id": auto.id}, message=f"Automation '{p.name}' created")

        reg.register(ToolDefinition(
            name="automation.create",
            description="Creates a lasting rule (trigger -> conditions -> actions), e.g. 'The next time you "
                        "see me, greet me by name', 'When you see me from tomorrow 9 am, remind me of the "
                        "rubbish' (once + not_before) or 'Remind me in 15 minutes to switch on the dryer' "
                        "(trigger at + speak).",
            parameters=CreateParams, category="automation", side_effect=SideEffect.WRITE,
            permissions=[Permission.AUTOMATION_MANAGE]), create)

        async def list_(_: NoParams, ctx: ToolContext) -> ToolResult:
            autos = await svc.list()
            return ToolResult.success([{"id": a.id, "name": a.name, "enabled": a.enabled,
                                        "description": a.description} for a in autos])

        reg.register(ToolDefinition(
            name="automation.list", description="Lists the automations.", parameters=NoParams,
            category="automation", permissions=[Permission.AUTOMATION_MANAGE]), list_)

        async def enable(p: EnableParams, ctx: ToolContext) -> ToolResult:
            await svc.update(p.automation_id, enabled=p.enabled)
            await engine.reload()
            return ToolResult.success(message="enabled" if p.enabled else "disabled")

        reg.register(ToolDefinition(
            name="automation.set_enabled", description="Enables or disables an automation.",
            parameters=EnableParams, category="automation", side_effect=SideEffect.WRITE,
            permissions=[Permission.AUTOMATION_MANAGE]), enable)

        async def delete(p: IdParams, ctx: ToolContext) -> ToolResult:
            await svc.delete(p.automation_id)
            await engine.reload()
            return ToolResult.success(message="deleted")

        reg.register(ToolDefinition(
            name="automation.delete", description="Deletes an automation (after confirmation).",
            parameters=IdParams, category="automation", side_effect=SideEffect.WRITE,
            requires_confirmation=True, permissions=[Permission.AUTOMATION_MANAGE]), delete)


def describe_schema() -> dict[str, Any]:
    from justai.automation.model import definition_schema

    schema: dict[str, Any] = json.loads(json.dumps(definition_schema()))
    return schema
