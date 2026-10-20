"""System, room and device tools."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from justai_sdk.permissions import Permission
from justai_sdk.tools import NoParams, SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from justai.container import Container

STARTED = time.time()


class DeviceFilter(BaseModel):
    room: str | None = Field(None, description="Room name or ID (optional)")
    capability: str | None = Field(None, description="z. B. video.input, audio.output, display.text")


class DeviceRef(BaseModel):
    device_id: str


def register(c: Container) -> None:
    reg = c.tools

    async def status(_: NoParams, ctx: ToolContext) -> ToolResult:
        runtimes = c.devices.runtimes()
        plugins = await c.plugins.list()
        return ToolResult.success({
            "uptime_s": int(time.time() - STARTED),
            "devices_online": sum(1 for r in runtimes if r.online),
            "devices_total": len(runtimes),
            "plugins_running": [p["id"] for p in plugins if p["running"]],
            "active_conversations": len(c.conversations.active()),
            "ai_cost_today_usd": round(c.usage.today_cost_usd, 4),
        })

    reg.register(ToolDefinition(
        name="system.status", description="System status: devices online, plugins, active conversations.",
        parameters=NoParams, category="system", permissions=[Permission.SYSTEM_READ]), status)

    async def capabilities(_: NoParams, ctx: ToolContext) -> ToolResult:
        tools = [{"name": t.definition.name, "description": t.definition.description}
                 for t in c.tools.available(ctx.permissions)]
        return ToolResult.success({"tools": tools,
                                   "providers": [f"{e.kind}:{e.id}" for e in c.providers.entries()]})

    reg.register(ToolDefinition(
        name="system.capabilities",
        description="Lists the assistant's available capabilities/tools (e.g. to check whether a tool for "
                    "a task already exists).",
        parameters=NoParams, category="system", permissions=[Permission.SYSTEM_READ]), capabilities)

    async def rooms(_: NoParams, ctx: ToolContext) -> ToolResult:
        devices = await c.device_records.list()
        out: list[dict[str, Any]] = []
        for room in await c.rooms.list():
            members = [d for d in devices if d.room_id == room.id]
            out.append({"id": room.id, "name": room.name, "current": room.id == ctx.room_id,
                        "devices": [{"id": d.id, "name": d.name, "status": d.status,
                                     "capabilities": d.capabilities} for d in members]})
        return ToolResult.success(out)

    reg.register(ToolDefinition(
        name="rooms.list", description="Rooms with their devices and capabilities.",
        parameters=NoParams, category="rooms", permissions=[Permission.DEVICES_READ]), rooms)

    async def devices(params: DeviceFilter, ctx: ToolContext) -> ToolResult:
        room_id = None
        if params.room:
            room = await c.rooms.find(params.room)
            if room is None:
                return ToolResult.failure("unknown_room", f"unknown room '{params.room}'")
            room_id = room.id
        items = []
        for d in await c.device_records.list(room_id=room_id):
            rt = c.devices.get(d.id)
            caps = sorted(rt.capabilities) if rt and rt.online else d.capabilities
            if params.capability and params.capability not in caps:
                continue
            items.append({"id": d.id, "name": d.name, "room_id": d.room_id,
                          "status": rt.status if rt else d.status, "capabilities": caps})
        return ToolResult.success(items)

    reg.register(ToolDefinition(
        name="devices.list", description="Devices (optionally filtered by room or capability).",
        parameters=DeviceFilter, category="devices", permissions=[Permission.DEVICES_READ]),
        devices)

    async def device_caps(params: DeviceRef, ctx: ToolContext) -> ToolResult:
        rt = c.devices.get(params.device_id)
        if rt is None:
            return ToolResult.failure("unknown_device", "Device not active")
        return ToolResult.success({"status": rt.status, "capabilities": sorted(rt.capabilities)})

    reg.register(ToolDefinition(
        name="devices.capabilities", description="Actual capabilities of a device (at runtime).",
        parameters=DeviceRef, category="devices", permissions=[Permission.DEVICES_READ],
        side_effect=SideEffect.READ), device_caps)
