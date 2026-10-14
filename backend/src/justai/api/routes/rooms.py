from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from justai.api.deps import Admin, C, User
from justai.rooms.service import RoomIn, RoomPatch

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


def _room(r: Any) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "slug": r.slug, "description": r.description,
            "floor": r.floor, "icon": r.icon, "layout": r.layout, "policy": r.policy}


@router.get("")
async def list_rooms(_: User, c: C) -> list[dict[str, Any]]:
    rooms = await c.rooms.list()
    devices = await c.device_records.list()
    endpoints = await c.endpoints.list()
    out = []
    for r in rooms:
        item = _room(r)
        item["devices"] = [d.id for d in devices if d.room_id == r.id]
        item["endpoints"] = [e.id for e in endpoints if e.room_id == r.id]
        out.append(item)
    return out


@router.post("")
async def create_room(body: RoomIn, p: Admin, c: C) -> dict[str, Any]:
    room = await c.rooms.create(body)
    await c.audit.record(p.actor, "room.create", room.id, name=room.name)
    await c.refresh_topology()
    return _room(room)


@router.patch("/{room_id}")
async def update_room(room_id: str, body: RoomPatch, p: Admin, c: C) -> dict[str, Any]:
    room = await c.rooms.update(room_id, body)
    await c.audit.record(p.actor, "room.update", room_id)
    await c.refresh_topology()
    return _room(room)


@router.delete("/{room_id}")
async def delete_room(room_id: str, p: Admin, c: C) -> dict[str, bool]:
    await c.rooms.delete(room_id)
    await c.audit.record(p.actor, "room.delete", room_id)
    await c.refresh_topology()
    return {"ok": True}
