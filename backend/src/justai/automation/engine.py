"""Automation engine.

Trigger matching happens on the event bus; execution goes through the durable job
queue (retries, restart recovery). Loop protection:

* events caused by an automation carry its id and an increased ``hop`` count;
  an automation never reacts to its own events, and deep chains are stopped
  (the bus additionally drops events above its global hop limit);
* cooldown, ``once`` and a per-hour run limit are enforced *before* a run is
  queued, so bursts of identical events cannot pile up.
"""

from __future__ import annotations

import asyncio
import builtins
import fnmatch
import time
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from justai_sdk.events import Event, EventSource
from justai_sdk.tools import InvocationOrigin, ToolContext
from pydantic import ValidationError
from sqlalchemy import select

from justai.auth.rbac import conversation_permissions
from justai.automation.cron import CronExpr
from justai.automation.model import (
    AtTrigger,
    AutomationDefinition,
    CallTool,
    CronTrigger,
    EmitEvent,
    EventTrigger,
    IntervalTrigger,
    InvokeAssistant,
    NoActiveConversation,
    PayloadCondition,
    ShowOnDisplay,
    Speak,
    StateCondition,
    TimeWindow,
    Wait,
)
from justai.common.errors import NotFound, ValidationFailed
from justai.db.engine import Database
from justai.db.models import Automation, AutomationRun
from justai.endpoints.service import DeviceRole
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.system.jobs import JobQueue

if TYPE_CHECKING:
    from justai.container import Container

log = get_logger(__name__)
MAX_CHAIN_HOPS = 4
# Automations that only announce something still give the person a moment to react.
ANNOUNCE_LISTEN_S = 4.0
SAY_EXACTLY = ("Sage jetzt wörtlich diesen Text und nichts weiter: „{text}“ "
               "Antwortet die Person danach, führe das Gespräch normal weiter.")


def _get_path(data: dict[str, Any], path: str) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def compare(left: Any, op: str, right: Any) -> bool:
    try:
        if op == "==":
            return bool(left == right)
        if op == "!=":
            return bool(left != right)
        if op == "in":
            return left in right
        if op == "contains":
            return right in left
        return bool({">": left > right, ">=": left >= right, "<": left < right, "<=": left <= right}[op])
    except TypeError:
        return False


class AutomationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def validate(definition: dict[str, Any]) -> AutomationDefinition:
        try:
            return AutomationDefinition.model_validate(definition)
        except ValidationError as exc:
            raise ValidationFailed("invalid automation", errors=[
                {"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]) from exc

    async def create_from_definition(self, *, name: str, description: str, definition: dict[str, Any],
                                     created_by: str, owner_person_id: str | None = None,
                                     origin: dict[str, Any] | None = None,
                                     enabled: bool = True) -> Automation:
        parsed = self.validate(definition)
        async with self.db.session() as s:
            auto = Automation(name=name, description=description,
                              definition=parsed.model_dump(mode="json", exclude_none=True),
                              created_by=created_by, owner_person_id=owner_person_id,
                              origin=origin or {}, enabled=enabled, state={})
            s.add(auto)
        return auto

    async def update(self, automation_id: str, **fields: Any) -> Automation:
        async with self.db.session() as s:
            auto = await s.get(Automation, automation_id)
            if auto is None:
                raise NotFound("automation not found")
            if fields.get("definition") is not None:
                fields["definition"] = self.validate(fields["definition"]).model_dump(
                    mode="json", exclude_none=True)
                auto.revision += 1
                auto.state = {}
            elif fields.get("enabled") is True and not auto.enabled:
                # Re-enabling a used-up "once" rule means: arm it again.
                auto.state = {**(auto.state or {}), "run_count": 0}
            for k, v in fields.items():
                if v is not None:
                    setattr(auto, k, v)
            await s.flush()
            await s.refresh(auto)  # load server-side updated_at before the session closes
            return auto

    async def delete(self, automation_id: str) -> None:
        async with self.db.session() as s:
            auto = await s.get(Automation, automation_id)
            if auto is None:
                raise NotFound("automation not found")
            await s.delete(auto)

    async def list(self) -> builtins.list[Automation]:
        async with self.db.session() as s:
            return list((await s.scalars(select(Automation).order_by(Automation.created_at))).all())

    async def get(self, automation_id: str) -> Automation:
        async with self.db.session() as s:
            auto = await s.get(Automation, automation_id)
        if auto is None:
            raise NotFound("automation not found")
        return auto

    async def runs(self, automation_id: str, limit: int = 50) -> builtins.list[AutomationRun]:
        async with self.db.session() as s:
            return list((await s.scalars(select(AutomationRun).where(
                AutomationRun.automation_id == automation_id)
                .order_by(AutomationRun.started_at.desc()).limit(limit))).all())


class AutomationEngine:
    def __init__(self, c: Container, service: AutomationService, bus: EventBus, jobs: JobQueue,
                 timezone: str = "Europe/Rome") -> None:
        self.c = c
        self.service = service
        self.bus = bus
        self.jobs = jobs
        self.tz = ZoneInfo(timezone)
        self._cache: list[tuple[Automation, AutomationDefinition]] = []
        self._recent_runs: dict[str, deque[float]] = {}
        self._scheduler: asyncio.Task[None] | None = None
        self._last_tick_minute: str | None = None
        self._unsubscribe: Any = None

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.load_timezone()
        await self.reload()
        self.jobs.register("automation.run", self._run_job)
        self._unsubscribe = self.bus.subscribe("*", self._on_event, name="automation-engine")
        self._scheduler = asyncio.create_task(self._schedule_loop(), name="automation-scheduler")

    async def stop(self) -> None:
        if self._scheduler:
            self._scheduler.cancel()
        if self._unsubscribe:
            self._unsubscribe()

    async def load_timezone(self) -> None:
        from justai.system.settings import SystemSettings

        try:
            raw = await self.c.settings_store.get("system")
            self.tz = ZoneInfo(SystemSettings.model_validate(raw or {}).timezone)
        except Exception as exc:
            log.warning("invalid timezone setting", keeping=str(self.tz), error=str(exc))

    async def reload(self) -> None:
        cache = []
        for auto in await self.service.list():
            if not auto.enabled:
                continue
            try:
                cache.append((auto, AutomationDefinition.model_validate(auto.definition)))
            except ValidationError as exc:
                log.error("stored automation invalid", automation=auto.id, error=str(exc))
        self._cache = cache

    # -------------------------------------------------------------- matching
    async def _on_event(self, event: Event) -> None:
        if event.type.startswith("automation.") or event.type in ("tool.executed", "conversation.state.changed"):
            return
        for auto, definition in list(self._cache):
            trig = definition.trigger
            if not isinstance(trig, EventTrigger):
                continue
            if not fnmatch.fnmatchcase(event.type, trig.event):
                continue
            if trig.room_id and event.source.room_id != trig.room_id:
                continue
            if any(_get_path(event.payload, k) != v for k, v in trig.match.items()):
                continue
            if event.source.kind == "automation" and event.source.id == auto.id:
                continue  # never react to own events
            if event.hop >= MAX_CHAIN_HOPS:
                log.warning("automation chain too deep", automation=auto.id, hop=event.hop)
                continue
            await self._maybe_queue(auto, definition, event)

    def _conditions_ok(self, definition: AutomationDefinition, event: Event | None) -> tuple[bool, str]:
        now = datetime.now(self.tz)
        for cond in definition.conditions:
            if isinstance(cond, TimeWindow):
                if cond.weekdays is not None and now.weekday() not in cond.weekdays:
                    return False, "weekday"
                t = now.time()
                inside = cond.start <= t <= cond.end if cond.start <= cond.end else (t >= cond.start or t <= cond.end)
                if not inside:
                    return False, "time_window"
            elif isinstance(cond, PayloadCondition):
                if event is None or not compare(_get_path(event.payload, cond.path), cond.op, cond.value):
                    return False, f"payload {cond.path}"
            elif isinstance(cond, NoActiveConversation):
                room = (event.source.room_id if event else None) if cond.room == "trigger" else cond.room
                if any(s.ctx.room_id == room for s in self.c.conversations.active()):
                    return False, "conversation active"
            elif isinstance(cond, StateCondition):
                pass  # evaluated asynchronously in _async_conditions
        return True, ""

    async def _async_conditions(self, definition: AutomationDefinition) -> tuple[bool, str]:
        for cond in definition.conditions:
            if isinstance(cond, StateCondition):
                vision = self.c.extensions.get("vision")
                if vision is None:
                    return False, "vision unavailable"
                current = await vision.states.current(cond.detector)
                if current["state"] != cond.state:
                    return False, f"state {cond.detector}={current['state']}"
        return True, ""

    async def _maybe_queue(self, auto: Automation, definition: AutomationDefinition,
                           event: Event | None, *, manual: bool = False) -> bool:
        opts = definition.options
        state = dict(auto.state or {})
        now = time.time()
        if not manual:
            if opts.expires_at and opts.expires_at < datetime.now(UTC):
                await self.service.update(auto.id, enabled=False)
                await self.reload()
                return False
            if opts.once and state.get("run_count", 0) >= 1:
                return False
            if now - float(state.get("last_triggered", 0)) < opts.cooldown_s:
                return False
            runs = self._recent_runs.setdefault(auto.id, deque())
            while runs and now - runs[0] > 3600:
                runs.popleft()
            if len(runs) >= opts.max_runs_per_hour:
                log.warning("automation rate limit reached", automation=auto.id)
                return False
            ok, _ = self._conditions_ok(definition, event)
            if not ok:
                return False
            ok, _ = await self._async_conditions(definition)
            if not ok:
                return False
            runs.append(now)
        state["last_triggered"] = now
        auto.state = state
        await self.service.update(auto.id, state=state)
        await self.jobs.enqueue(
            "automation.run",
            {"automation_id": auto.id, "event": event.model_dump(mode="json") if event else None,
             "manual": manual},
            priority=opts.priority, max_attempts=opts.max_retries + 1,
            dedup_key=f"auto:{auto.id}:{event.id if event else now}")
        return True

    async def run_now(self, automation_id: str) -> None:
        auto = await self.service.get(automation_id)
        definition = AutomationDefinition.model_validate(auto.definition)
        await self._maybe_queue(auto, definition, None, manual=True)

    # ------------------------------------------------------------- schedule
    async def _schedule_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            now = datetime.now(self.tz)
            minute_key = now.strftime("%Y%m%d%H%M")
            new_minute = minute_key != self._last_tick_minute
            self._last_tick_minute = minute_key
            for auto, definition in list(self._cache):
                trig = definition.trigger
                fire = False
                if isinstance(trig, CronTrigger) and new_minute:
                    fire = CronExpr(trig.cron).matches(now)
                elif isinstance(trig, IntervalTrigger):
                    fire = time.time() - float((auto.state or {}).get("last_triggered", 0)) >= trig.seconds
                elif isinstance(trig, AtTrigger):
                    at = trig.at if trig.at.tzinfo else trig.at.replace(tzinfo=self.tz)
                    fire = at <= now and not (auto.state or {}).get("run_count")
                if fire:
                    tick = Event(type="schedule.tick", payload={"automation_id": auto.id},
                                 source=EventSource(kind="system", room_id=getattr(trig, "room_id", None)))
                    await self._maybe_queue(auto, definition, tick)

    # ------------------------------------------------------------- execution
    async def _run_job(self, payload: dict[str, Any]) -> None:
        auto = await self.service.get(payload["automation_id"])
        definition = AutomationDefinition.model_validate(auto.definition)
        event = Event.model_validate(payload["event"]) if payload.get("event") else None
        async with self.c.db.session() as s:
            run = AutomationRun(automation_id=auto.id, event_id=event.id if event else None,
                                status="running", attempts=1)
            s.add(run)
            await s.flush()
            run_id = run.id
        log_entries: list[dict[str, Any]] = []

        def note(msg: str) -> None:
            log_entries.append({"t": datetime.now(UTC).isoformat(timespec="seconds"), "msg": msg})

        await self._publish(auto, event, "automation.run.started", {"run_id": run_id})
        try:
            for action in definition.actions:
                await self._execute(auto, action, event, note)
        except Exception as exc:
            note(f"Fehler: {exc}")
            await self._finish_run(run_id, "failed", log_entries, str(exc))
            await self._publish(auto, event, "automation.run.finished", {"run_id": run_id, "status": "failed"})
            raise
        await self._finish_run(run_id, "succeeded", log_entries, None)
        state = dict(auto.state or {})
        state["run_count"] = int(state.get("run_count", 0)) + 1
        state["last_run_at"] = datetime.now(UTC).isoformat()
        disable = definition.options.once and not payload.get("manual")
        await self.service.update(auto.id, state=state, enabled=False if disable else None)
        if disable:
            await self.reload()
        await self._publish(auto, event, "automation.run.finished", {"run_id": run_id, "status": "succeeded"})

    async def _finish_run(self, run_id: str, status: str, entries: list[dict[str, Any]],
                          error: str | None) -> None:
        async with self.c.db.session() as s:
            run = await s.get(AutomationRun, run_id)
            if run:
                run.status, run.log, run.error = status, entries, error
                run.finished_at = datetime.now(UTC)

    async def _publish(self, auto: Automation, trigger: Event | None, type: str, payload: dict[str, Any]) -> None:
        source = EventSource(kind="automation", id=auto.id,
                             room_id=trigger.source.room_id if trigger else None)
        payload = {"automation_id": auto.id, "name": auto.name, **payload}
        event = trigger.caused(type, payload, source=source) if trigger else Event(
            type=type, payload=payload, source=source)
        await self.bus.publish(event)

    def _room(self, spec: str, event: Event | None) -> str | None:
        if spec == "trigger":
            return event.source.room_id if event else None
        return spec

    async def _endpoint_for_room(self, room_id: str, event: Event | None) -> str | None:
        if event and event.source.endpoint_id:
            return event.source.endpoint_id
        candidates = [e for e in await self.c.endpoints.list(room_id=room_id)
                      if e.enabled and e.primary(DeviceRole.SPEAKER) and e.id in self.c.audio.endpoints]
        candidates.sort(key=lambda e: -e.priority)
        if not candidates:
            return None
        # Prefer the endpoint whose camera saw the trigger.
        if event and event.source.device_id:
            for e in candidates:
                if event.source.device_id in e.device_ids(DeviceRole.CAMERA):
                    return e.id
        return candidates[0].id

    async def _converse(self, endpoint_id: str, instruction: str, person_id: str | None,
                        listen: bool) -> None:
        session = await self.c.conversations.start(endpoint_id, trigger="automation",
                                                   instruction=instruction, person_id=person_id)
        if not listen:
            session.sm.inactivity_timeout_s = min(session.sm.inactivity_timeout_s, ANNOUNCE_LISTEN_S)

    async def _execute(self, auto: Automation, action: Any, event: Event | None,
                       note: Any) -> None:
        c = self.c
        if isinstance(action, InvokeAssistant):
            room_id = self._room(action.room, event)
            if room_id is None:
                raise ValueError("no room for assistant.invoke")
            endpoint_id = await self._endpoint_for_room(room_id, event)
            if endpoint_id is None:
                raise ValueError("no interaction endpoint with a speaker in the target room")
            person_id = (event.payload.get("person_id") if event else None) or auto.owner_person_id
            await self._converse(endpoint_id, action.instruction, person_id, action.start_conversation)
            note(f"Assistent in {room_id} aktiviert")
        elif isinstance(action, Speak):
            room_id = self._room(action.room, event)
            endpoint_id = await self._endpoint_for_room(room_id, event) if room_id else None
            if action.start_conversation and endpoint_id is not None:
                # Same voice as in conversations, and the person can answer right away.
                person_id = (event.payload.get("person_id") if event else None) or auto.owner_person_id
                await self._converse(endpoint_id, SAY_EXACTLY.format(text=action.text), person_id, True)
                note(f"Gesprochen (Gespräch) in {room_id}: {action.text[:60]}")
            else:
                speech = c.extensions["speech"]
                decision = speech.resolve(target_room_id=room_id, system=True)
                await speech.say(action.text, decision)
                note(f"Gesagt in {room_id}: {action.text[:60]}")
        elif isinstance(action, ShowOnDisplay):
            room_id = self._room(action.room, event)
            display = c.extensions.get("display")
            if display is None:
                raise ValueError("displays unavailable")
            pres = await display.present(action.document, target_room_id=room_id, system=True,
                                         source=f"automation:{auto.id}")
            note(f"Darstellung {pres.id}: {pres.status}")
        elif isinstance(action, CallTool):
            ctx = ToolContext(call_id=f"auto-{auto.id}", origin=InvocationOrigin.AUTOMATION,
                              automation_id=auto.id, room_id=event.source.room_id if event else None,
                              person_id=auto.owner_person_id,
                              permissions=conversation_permissions("resident", None))
            result = await c.executor.execute(action.name, action.args, ctx)
            if not result.ok:
                raise ValueError(f"tool {action.name} failed: {result.message}")
            note(f"Tool {action.name}: {result.message or 'ok'}")
        elif isinstance(action, EmitEvent):
            source = EventSource(kind="automation", id=auto.id, room_id=event.source.room_id if event else None)
            new = event.caused(action.event, action.payload, source=source) if event else Event(
                type=action.event, payload=action.payload, source=source)
            await self.bus.publish(new)
            note(f"Ereignis {action.event}")
        elif isinstance(action, Wait):
            await asyncio.sleep(action.seconds)
