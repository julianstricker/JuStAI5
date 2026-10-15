"""Displays: browser display gateway, presentation lifecycle, routing.

Presentation lifecycle: CREATED -> SENT -> DISPLAYED (ack from the display) ->
UPDATED -> CLOSED, or FAILED. The assistant reports success only after the
display acknowledged the rendering (acceptance criterion 15).
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from fastapi import WebSocket
from justai_sdk.events import Event, EventSource
from justai_sdk.ports.devices import BaseDeviceHandle, DeviceHealth, ProbeResult
from sqlalchemy import select

from justai.common.errors import NotFound, RoutingDenied, Unavailable
from justai.db.models import Device, Presentation
from justai.devices.service import DeviceIn
from justai.display.components import ComponentRegistry
from justai.logging import get_logger
from justai.output.router import OutputKind, OutputRequest

if TYPE_CHECKING:
    from justai.container import Container

log = get_logger(__name__)

DRIVER_ID = "browser-display"
ACK_TIMEOUT_S = 8.0


@dataclass
class Connection:
    ws: WebSocket
    device_id: str | None
    capabilities: list[str]
    user_agent: str
    pairing_code: str | None = None
    since: float = field(default_factory=time.time)
    acks: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    current: str | None = None

    async def send(self, msg: dict[str, Any]) -> None:
        await self.ws.send_json(msg)


class BrowserDisplayHandle(BaseDeviceHandle):
    def __init__(self, device_id: str, caps: set[str], service: DisplayService) -> None:
        super().__init__(device_id, caps)
        self.service = service

    async def health(self) -> DeviceHealth:
        return DeviceHealth(online=self.device_id in self.service.connections,
                            detail=None if self.device_id in self.service.connections else "display not connected")


class BrowserDisplayDriver:
    """Core-internal driver: a browser display is online while its WebSocket is connected."""

    driver_id = DRIVER_ID
    display_name = "Browser-Display"

    def __init__(self, service: DisplayService) -> None:
        self.service = service

    def config_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"capabilities": {"type": "array"}}}

    def secret_fields(self) -> list[str]:
        return ["token"]

    async def probe(self, config: dict[str, Any]) -> ProbeResult:
        return ProbeResult(ok=True, capabilities=list(config.get("capabilities") or ["display.text"]))

    async def open(self, device_id: str, config: dict[str, Any], probe: ProbeResult) -> BrowserDisplayHandle:
        return BrowserDisplayHandle(device_id, set(probe.capabilities), self.service)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class DisplayService:
    def __init__(self, c: Container, components: ComponentRegistry) -> None:
        self.c = c
        self.components = components
        self.connections: dict[str, Connection] = {}  # device_id -> connection
        self.pending: dict[str, Connection] = {}  # pairing code -> connection
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._indicator_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self.c.providers.register("device_driver", BrowserDisplayDriver(self), "core")
        self._indicator_task = asyncio.create_task(self._indicators(), name="display-indicators")

    async def stop(self) -> None:
        if self._indicator_task:
            self._indicator_task.cancel()
        for conn in list(self.connections.values()):
            with contextlib.suppress(Exception):
                await conn.ws.close()

    # ---------------------------------------------------------- websocket gateway
    async def handle_socket(self, ws: WebSocket) -> None:
        await ws.accept()
        conn: Connection | None = None
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=15)
            if hello.get("type") != "hello":
                await ws.close(code=4400)
                return
            caps = [str(x) for x in hello.get("capabilities") or [] if str(x).startswith("display.")]
            conn = Connection(ws=ws, device_id=None, capabilities=caps,
                              user_agent=str(hello.get("user_agent", ""))[:300])
            token = hello.get("token")
            device = await self._device_for_token(token) if token else None
            if token and device is None:
                await conn.send({"type": "error", "message": "invalid token"})
            if device is not None:
                await self._attach(conn, device)
            else:
                code = f"{secrets.randbelow(1_000_000):06d}"
                conn.pairing_code = code
                self.pending[code] = conn
                await conn.send({"type": "pairing", "code": code})
            while True:
                msg = await ws.receive_json()
                await self._on_message(conn, msg)
        except Exception as exc:
            if not isinstance(exc, (asyncio.CancelledError,)) and "disconnect" not in type(exc).__name__.lower():
                log.info("display connection closed", error=str(exc))
        finally:
            if conn is not None:
                if conn.pairing_code:
                    self.pending.pop(conn.pairing_code, None)
                if conn.device_id and self.connections.get(conn.device_id) is conn:
                    del self.connections[conn.device_id]
                    await self.c.bus.publish(Event(type="display.disconnected",
                                                   payload={"device_id": conn.device_id}))
                    with contextlib.suppress(Exception):
                        await self.c.devices.reload(conn.device_id)

    async def _device_for_token(self, token: str) -> Device | None:
        async with self.c.db.session() as s:
            devices = (await s.scalars(select(Device).where(Device.driver_id == DRIVER_ID))).all()
        wanted = _hash(token)
        for d in devices:
            if secrets.compare_digest(str(d.config.get("token_hash", "")), wanted):
                return d
        return None

    async def _attach(self, conn: Connection, device: Device) -> None:
        conn.device_id = device.id
        old = self.connections.get(device.id)
        if old is not None and old is not conn:
            with contextlib.suppress(Exception):
                await old.ws.close()
        self.connections[device.id] = conn
        if sorted(device.config.get("capabilities") or []) != sorted(conn.capabilities):
            from justai.devices.service import DevicePatch

            await self.c.device_records.update(device.id, DevicePatch(
                config={**device.config, "capabilities": conn.capabilities}), [])
        await self.c.devices.reload(device.id)
        rooms = {r.id: r.name for r in await self.c.rooms.list()}
        await conn.send({"type": "ready", "name": device.name, "room": rooms.get(device.room_id or "")})
        await self.c.bus.publish(Event(type="display.connected", payload={"device_id": device.id},
                                       source=EventSource(kind="display", device_id=device.id,
                                                          room_id=device.room_id)))

    async def approve(self, code: str, name: str, room_id: str | None) -> str:
        conn = self.pending.pop(code, None)
        if conn is None:
            raise NotFound("pairing code expired")
        token = secrets.token_urlsafe(32)
        device = await self.c.device_records.create(DeviceIn(
            name=name, driver_id=DRIVER_ID, room_id=room_id,
            config={"capabilities": conn.capabilities, "token_hash": _hash(token),
                    "user_agent": conn.user_agent}), [])
        conn.pairing_code = None
        await conn.send({"type": "paired", "token": token, "name": name, "room": None})
        await self._attach(conn, device)
        await self.c.refresh_topology()
        return device.id

    async def _on_message(self, conn: Connection, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "ack":
            fut = conn.acks.pop(str(msg.get("presentation_id")), None)
            if fut is not None and not fut.done():
                fut.set_result(str(msg.get("status", "displayed")))
        elif kind == "interaction" and conn.device_id:
            await self._interaction(conn, msg)

    # ------------------------------------------------------------- presentations
    async def present(self, document: dict[str, Any], *, origin_endpoint_id: str | None = None,
                      origin_room_id: str | None = None, target_room_id: str | None = None,
                      target_device_id: str | None = None, explicit_cross_room: bool = False,
                      permissions: frozenset[str] = frozenset(), system: bool = False,
                      personal: bool = False, allow_personal: bool = False,
                      session_id: str | None = None, source: str = "assistant") -> Presentation:
        normalized, needed = self.components.normalize(document)
        decision = self.c.output.route(OutputRequest(
            OutputKind.DISPLAY, origin_endpoint_id=origin_endpoint_id, origin_room_id=origin_room_id,
            target_room_id=target_room_id, target_device_id=target_device_id,
            explicit_cross_room=explicit_cross_room, permissions=permissions, admin=system,
            personal_content=personal, allow_personal_on_shared=allow_personal,
            required_capabilities=frozenset(needed)))
        device_id = decision.device_id
        normalized = self._inject_media_urls(normalized, permissions, system)
        duration = normalized.get("duration_s")
        async with self.c.db.session() as s:
            pres = Presentation(display_device_id=device_id, room_id=decision.room_id, session_id=session_id,
                                document=normalized, status="created",
                                sensitivity="personal" if personal else "normal",
                                expires_at=datetime.now(UTC) + timedelta(seconds=duration) if duration else None)
            s.add(pres)
            await s.flush()
            pres_id = pres.id
        status = await self._send(device_id, pres_id, normalized)
        pres = await self._set_status(pres_id, status)
        if status == "displayed" and duration:
            self._timers[pres_id] = asyncio.create_task(self._auto_close(device_id, pres_id, duration))
        await self.c.audit.record(source, "display.present", device_id, presentation=pres_id, status=status)
        return pres

    def _inject_media_urls(self, doc: dict[str, Any], permissions: frozenset[str], system: bool) -> dict[str, Any]:
        """Camera components get a short-lived signed stream URL (only with camera.read)."""

        def walk(component: dict[str, Any]) -> dict[str, Any]:
            if component.get("type") == "camera":
                if not system and "camera.read" not in permissions:
                    raise RoutingDenied("showing a camera stream needs camera.read")
                token = self.c.auth.issue_scoped_token(component["device_id"], "display-camera",
                                                      timedelta(hours=1))
                return {**component, "src": f"/api/display/camera/{component['device_id']}.mp4?token={token}"}
            if "children" in component:
                return {**component, "children": [walk(ch) for ch in component["children"]]}
            return component

        return {**doc, "components": [walk(c) for c in doc["components"]]}

    async def _send(self, device_id: str, pres_id: str, document: dict[str, Any]) -> str:
        conn = self.connections.get(device_id)
        if conn is None:
            return "failed"
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        conn.acks[pres_id] = fut
        try:
            await conn.send({"type": "show", "presentation_id": pres_id, "document": document})
            await self._set_status(pres_id, "sent")
            status = await asyncio.wait_for(fut, timeout=ACK_TIMEOUT_S)
        except TimeoutError:
            status = "failed"
        except Exception as exc:
            log.warning("display send failed", device=device_id, error=str(exc))
            status = "failed"
        finally:
            conn.acks.pop(pres_id, None)
        if status == "displayed":
            previous, conn.current = conn.current, pres_id
            if previous and previous != pres_id:
                await self._set_status(previous, "closed")
        return status

    async def update(self, pres_id: str, document: dict[str, Any]) -> Presentation:
        async with self.c.db.session() as s:
            pres = await s.get(Presentation, pres_id)
        if pres is None or pres.status == "closed":
            raise NotFound("presentation not active")
        normalized, _ = self.components.normalize(document)
        status = await self._send(pres.display_device_id, pres_id, normalized)
        async with self.c.db.session() as s:
            row = await s.get(Presentation, pres_id)
            if row:
                row.document = normalized
        return await self._set_status(pres_id, "updated" if status == "displayed" else "failed")

    async def close(self, device_id: str, pres_id: str) -> None:
        conn = self.connections.get(device_id)
        if conn is not None:
            with contextlib.suppress(Exception):
                await conn.send({"type": "close", "presentation_id": pres_id})
            if conn.current == pres_id:
                conn.current = None
        timer = self._timers.pop(pres_id, None)
        if timer and timer is not asyncio.current_task():
            timer.cancel()
        await self._set_status(pres_id, "closed")

    async def _auto_close(self, device_id: str, pres_id: str, seconds: float) -> None:
        await asyncio.sleep(seconds)
        await self.close(device_id, pres_id)

    async def _set_status(self, pres_id: str, status: str, error: str | None = None) -> Presentation:
        now = datetime.now(UTC)
        async with self.c.db.session() as s:
            pres = await s.get(Presentation, pres_id)
            if pres is None:
                raise NotFound("presentation not found")
            pres.status = status
            if status == "sent":
                pres.sent_at = now
            elif status == "displayed":
                pres.displayed_at = now
            elif status == "updated":
                pres.updated_at = now
            elif status == "closed":
                pres.closed_at = now
            elif status == "failed":
                pres.error = error or "display did not acknowledge"
        await self.c.bus.publish(Event(type="display.presentation.status", payload={
            "presentation_id": pres_id, "status": status, "device_id": pres.display_device_id},
            source=EventSource(kind="display", device_id=pres.display_device_id, room_id=pres.room_id,
                               session_id=pres.session_id)))
        return pres

    async def _interaction(self, conn: Connection, msg: dict[str, Any]) -> None:
        pres_id = str(msg.get("presentation_id", ""))
        async with self.c.db.session() as s:
            pres = await s.get(Presentation, pres_id)
        if pres is None:
            return
        payload = {"presentation_id": pres_id, "device_id": conn.device_id,
                   "component": str(msg.get("component", ""))[:32],
                   "option_id": msg.get("option_id"), "action_id": msg.get("action_id"),
                   "label": str(msg.get("label", ""))[:200]}
        await self.c.bus.publish(Event(type="display.interaction", payload=payload, source=EventSource(
            kind="display", device_id=conn.device_id, room_id=pres.room_id, session_id=pres.session_id)))
        session = self.c.conversations.get(pres.session_id) if pres.session_id else None
        if session is not None:
            await session.inject(f"Der Benutzer hat auf dem Display '{payload['label']}' gewählt.")

    async def list(self) -> builtins.list[dict[str, Any]]:
        devices = [d for d in await self.c.device_records.list() if d.driver_id == DRIVER_ID or
                   any(cap.startswith("display.") for cap in d.capabilities)]
        out = []
        async with self.c.db.session() as s:
            for d in devices:
                conn = self.connections.get(d.id)
                current = await s.get(Presentation, conn.current) if conn and conn.current else None
                rt = self.c.devices.get(d.id)
                out.append({"device_id": d.id, "name": d.name, "room_id": d.room_id,
                            "status": rt.status if rt else d.status, "connected": conn is not None,
                            "capabilities": sorted(rt.capabilities) if rt and rt.online else d.capabilities,
                            "presentation": {"id": current.id, "status": current.status,
                                             "title": current.document.get("title")} if current else None})
        return out

    def pending_list(self) -> builtins.list[dict[str, Any]]:
        return [{"code": code, "user_agent": c.user_agent, "capabilities": c.capabilities,
                 "since": datetime.fromtimestamp(c.since, UTC).isoformat()} for code, c in self.pending.items()]

    async def presentations(self, limit: int = 50) -> builtins.list[Presentation]:
        async with self.c.db.session() as s:
            return list((await s.scalars(select(Presentation).order_by(Presentation.created_at.desc())
                                         .limit(limit))).all())

    async def _indicators(self) -> None:
        """Tell displays what is active in their room (privacy indicator)."""
        while True:
            await asyncio.sleep(2)
            for device_id, conn in list(self.connections.items()):
                rt = self.c.devices.get(device_id)
                room = rt.room_id if rt else None
                listening = any(ep.room_id == room and ep.has_input for ep in self.c.audio.endpoints.values())
                sessions = [s for s in self.c.conversations.active() if s.ctx.room_id == room]
                with contextlib.suppress(Exception):
                    await conn.send({"type": "indicator", "listening": listening,
                                     "conversation": bool(sessions),
                                     "cloud": any(s.mode == "realtime" for s in sessions)})

    def require_connected(self, device_id: str) -> Connection:
        conn = self.connections.get(device_id)
        if conn is None:
            raise Unavailable("display not connected")
        return conn
