"""System status, events, tools, audit, metrics and live updates."""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime
from typing import Any

import psutil
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse, StreamingResponse
from justai_sdk.events import Event, EventSource
from justai_sdk.tools import InvocationOrigin, ToolContext
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from justai.api.deps import COOKIE, Admin, C, User
from justai.audio.io import wav_stream_header
from justai.common.errors import NotFound, Unauthorized
from justai.common.redact import redact

router = APIRouter(tags=["system"])
STARTED = time.time()


class ManualEvent(BaseModel):
    type: str = Field(pattern=r"^[a-z][a-z0-9_.]+$")
    payload: dict[str, Any] = {}
    room_id: str | None = None
    device_id: str | None = None


class ToolCallIn(BaseModel):
    args: dict[str, Any] = {}
    room_id: str | None = None
    endpoint_id: str | None = None
    confirmed: bool = False


def _event(e: Event) -> dict[str, Any]:
    return redact(e.model_dump(mode="json"))  # type: ignore[no-any-return]


@router.get("/api/health")
async def health(c: C) -> dict[str, Any]:
    return {"ok": True, "db": await c.db.ping(), "go2rtc": await c.go2rtc.healthy()}


@router.get("/api/system/status")
async def status(_: User, c: C) -> dict[str, Any]:
    proc = psutil.Process()
    devices = c.devices.runtimes()
    plugins = await c.plugins.list()
    return {
        "version": "0.1.0", "uptime_s": int(time.time() - STARTED),
        "resources": {"cpu_percent": psutil.cpu_percent(interval=None),
                      "process_cpu_percent": proc.cpu_percent(interval=None),
                      "memory_mb": round(proc.memory_info().rss / 1e6, 1),
                      "system_memory_percent": psutil.virtual_memory().percent,
                      "load_avg": list(psutil.getloadavg())},
        "devices": {"total": len(devices), "online": sum(1 for d in devices if d.online)},
        "plugins": {"total": len(plugins), "running": sum(1 for p in plugins if p["running"]),
                    "failed": [p["id"] for p in plugins if p["status"] == "failed"]},
        "conversations": len(c.conversations.active()),
        "tasks": [vars(t) for t in c.supervisor.status()],
        "events": {"published": c.bus.stats.published, "persisted": c.bus.stats.persisted,
                   "duplicates": c.bus.stats.duplicates, "loops_stopped": c.bus.stats.loops_stopped,
                   "subscribers": c.bus.subscriber_stats()},
        "ai_cost_today_usd": round(c.usage.today_cost_usd, 4),
        "go2rtc": await c.go2rtc.healthy(),
        "privacy": privacy_indicators(c),
    }


def privacy_indicators(c: Any) -> list[dict[str, Any]]:
    """What is being used right now - shown in the admin UI and on displays."""
    items = []
    for ep in c.audio.endpoints.values():
        session = c.conversations.for_endpoint(ep.id)
        items.append({
            "endpoint_id": ep.id, "room_id": ep.room_id,
            "wakeword_local": ep.has_input and ep.processor.wakeword.enabled,
            "conversation_active": session is not None,
            "cloud_audio": bool(session and session.mode == "realtime"),
            "muted": ep.processor.muted,
        })
    vision = c.extensions.get("vision")
    if vision is not None:
        for cam in vision.active_cameras():
            items.append({"device_id": cam, "vision_local": True})
    return items


@router.get("/api/metrics", response_class=PlainTextResponse)
async def metrics(_: Admin) -> PlainTextResponse:
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/events/recent")
async def recent_events(_: User, c: C, limit: int = 100, pattern: str = "*") -> list[dict[str, Any]]:
    return [_event(e) for e in c.bus.recent(limit, pattern)]


@router.get("/api/events")
async def stored_events(_: User, c: C, type: str | None = None, prefix: str | None = None,
                        room_id: str | None = None, correlation_id: str | None = None,
                        since: datetime | None = None, limit: int = 100) -> list[dict[str, Any]]:
    rows = await c.event_store.query(types=[type] if type else None, type_prefix=prefix,
                                     room_id=room_id, correlation_id=correlation_id,
                                     since=since, limit=limit)
    return [{"id": r.id, "type": r.type, "ts": r.ts, "source": r.source, "payload": r.payload,
             "correlation_id": r.correlation_id, "hop": r.hop} for r in rows]


@router.get("/api/events/catalog")
async def catalog(_: User, c: C) -> list[dict[str, Any]]:
    return [{"type": s.type, "description": s.description, "durable": s.durable,
             "owner": s.owner, "sensitivity": str(s.sensitivity),
             "payload_schema": s.payload_model.model_json_schema() if s.payload_model else None}
            for s in c.bus.catalog.all()]


@router.post("/api/events")
async def publish_event(body: ManualEvent, p: Admin, c: C) -> dict[str, Any]:
    event = Event(type=body.type, payload=body.payload,
                  source=EventSource(kind="user", user_id=p.user_id, room_id=body.room_id,
                                     device_id=body.device_id))
    accepted = await c.bus.publish(event)
    await c.audit.record(p.actor, "event.publish", body.type)
    return {"id": event.id, "accepted": accepted}


@router.get("/api/tools")
async def tools(_: User, c: C) -> list[dict[str, Any]]:
    return [{"name": t.definition.name, "description": t.definition.description,
             "category": t.definition.category, "owner": t.owner,
             "permissions": t.definition.permissions,
             "side_effect": str(t.definition.side_effect),
             "requires_confirmation": t.definition.requires_confirmation,
             "parameters": t.definition.parameters_schema()} for t in c.tools.list()]


@router.post("/api/tools/{name}/execute")
async def execute_tool(name: str, body: ToolCallIn, p: Admin, c: C) -> dict[str, Any]:
    """Diagnostics: run a tool with the admin's permissions in a chosen room context."""
    ctx = ToolContext(call_id=f"admin-{int(time.time() * 1000)}", origin=InvocationOrigin.ADMIN,
                      user_id=p.user_id, room_id=body.room_id, endpoint_id=body.endpoint_id,
                      permissions=p.permissions, confirmed=body.confirmed)
    result = await c.executor.execute(name, body.args, ctx)
    return result.model_dump(mode="json")


@router.get("/api/tools/executions")
async def tool_executions(_: Admin, c: C, limit: int = 100) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from justai.db.models import ToolExecution

    async with c.db.session() as s:
        rows = (await s.scalars(select(ToolExecution).order_by(ToolExecution.created_at.desc())
                                .limit(limit))).all()
    return [{"id": r.id, "tool": r.tool, "origin": r.origin, "status": r.status,
             "session_id": r.session_id, "room_id": r.room_id, "params": r.params,
             "result": r.result, "error": r.error, "duration_ms": r.duration_ms,
             "created_at": r.created_at} for r in rows]


@router.get("/api/audit")
async def audit(_: Admin, c: C, limit: int = 200, prefix: str | None = None) -> list[dict[str, Any]]:
    return [{"ts": a.ts, "actor": a.actor, "action": a.action, "target": a.target,
             "detail": a.detail} for a in await c.audit.list(limit, prefix)]


@router.get("/api/telemetry")
async def telemetry(_: User, c: C, prefix: str = "") -> dict[str, Any]:
    return c.telemetry.snapshot(prefix)


@router.websocket("/api/ws")
async def live(ws: WebSocket) -> None:
    """Live feed for the admin UI: events and telemetry."""
    c = ws.app.state.container
    token = ws.cookies.get(COOKIE) or ws.query_params.get("token")
    try:
        if not token:
            raise Unauthorized()
        await c.auth.authenticate(token)
    except Exception:
        await ws.close(code=4401)
        return
    await ws.accept()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)

    async def on_event(e: Event) -> None:
        if queue.full():
            return
        queue.put_nowait({"kind": "event", "event": _event(e)})

    unsubscribe = c.bus.subscribe("*", on_event, name="admin-ws")
    tq = c.telemetry.subscribe()
    last_sent: dict[str, float] = {}

    async def pump_telemetry() -> None:
        while True:
            msg = await tq.get()
            now = time.monotonic()
            if now - last_sent.get(msg["topic"], 0) < 0.2:
                continue
            last_sent[msg["topic"]] = now
            if not queue.full():
                queue.put_nowait({"kind": "telemetry", **msg})

    pump = asyncio.create_task(pump_telemetry())
    try:
        while True:
            msg = await queue.get()
            await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        unsubscribe()
        c.telemetry.unsubscribe(tq)
        pump.cancel()
        with contextlib.suppress(Exception):
            await ws.close()


@router.get("/internal/talkback/{token}.wav", include_in_schema=False)
async def talkback(token: str, c: C) -> StreamingResponse:
    """Endless real-time WAV stream pulled by go2rtc for camera speakers."""
    queue = c.talkback.get(token)
    stats = c.talkback.stats.get(token)
    if queue is None or stats is None:
        raise NotFound()

    async def body():  # type: ignore[no-untyped-def]
        stats.connections += 1
        stats.connected = True
        stats.last_pull = time.monotonic()
        try:
            yield wav_stream_header(16000)
            while True:
                data = await queue.get()
                if data is None:
                    return
                stats.bytes_pulled += len(data)
                stats.last_pull = time.monotonic()
                yield data
        finally:
            stats.connected = False

    return StreamingResponse(body(), media_type="audio/wav")
