"""Room management. Rooms are the organising unit for devices and output routing."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from justai.common.errors import Conflict, NotFound
from justai.db.engine import Database
from justai.db.models import Room


class RoomPolicy(BaseModel):
    """Per-room privacy/routing policy."""

    shared_space: bool = True  # private content is not shown on displays in shared spaces
    vision_allowed: bool = True
    face_recognition_allowed: bool = True
    cloud_media_allowed: bool = True  # camera images/audio from this room may go to cloud AI
    announcements_allowed: bool = True  # may receive cross-room announcements


class RoomIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = ""
    floor: str | None = None
    icon: str | None = None
    layout: dict[str, Any] = Field(default_factory=dict)
    policy: RoomPolicy = Field(default_factory=RoomPolicy)


class RoomPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    floor: str | None = None
    icon: str | None = None
    layout: dict[str, Any] | None = None
    policy: RoomPolicy | None = None


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or "room"


class RoomService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def list(self) -> list[Room]:
        async with self.db.session() as s:
            return list((await s.scalars(select(Room).order_by(Room.name))).all())

    async def get(self, room_id: str) -> Room:
        async with self.db.session() as s:
            room = await s.get(Room, room_id)
        if room is None:
            raise NotFound(f"room {room_id} not found")
        return room

    async def find(self, name_or_id: str) -> Room | None:
        """Resolve a room by id, slug or (case-insensitive) name."""
        key = name_or_id.strip()
        async with self.db.session() as s:
            room = await s.get(Room, key)
            if room:
                return room
            rooms = (await s.scalars(select(Room))).all()
        slug = slugify(key)
        for r in rooms:
            if r.slug == slug or r.name.lower() == key.lower():
                return r
        return None

    async def create(self, data: RoomIn) -> Room:
        slug = slugify(data.name)
        async with self.db.session() as s:
            if await s.scalar(select(Room).where(Room.slug == slug)):
                raise Conflict(f"room '{data.name}' exists")
            room = Room(name=data.name, slug=slug, description=data.description,
                        floor=data.floor, icon=data.icon, layout=data.layout,
                        policy=data.policy.model_dump())
            s.add(room)
        return room

    async def update(self, room_id: str, patch: RoomPatch) -> Room:
        async with self.db.session() as s:
            room = await s.get(Room, room_id)
            if room is None:
                raise NotFound(f"room {room_id} not found")
            if patch.name is not None:
                new_slug = slugify(patch.name)
                clash = await s.scalar(select(Room).where(Room.slug == new_slug, Room.id != room_id))
                if clash:
                    raise Conflict(f"room '{patch.name}' exists")
                room.name, room.slug = patch.name, new_slug
            for field in ("description", "floor", "icon", "layout"):
                value = getattr(patch, field)
                if value is not None:
                    setattr(room, field, value)
            if patch.policy is not None:
                room.policy = patch.policy.model_dump()
            return room

    async def delete(self, room_id: str) -> None:
        async with self.db.session() as s:
            room = await s.get(Room, room_id)
            if room is None:
                raise NotFound(f"room {room_id} not found")
            await s.delete(room)

    @staticmethod
    def policy(room: Room) -> RoomPolicy:
        return RoomPolicy.model_validate(room.policy or {})
