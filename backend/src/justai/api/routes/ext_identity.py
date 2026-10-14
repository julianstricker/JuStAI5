from __future__ import annotations

import asyncio
from typing import Any

import cv2
import numpy as np
from fastapi import APIRouter, Response
from pydantic import BaseModel

from justai.api.deps import Admin, C, User
from justai.common.errors import Unavailable, ValidationFailed
from justai.identity.service import PersonIn, PersonPatch

router = APIRouter(prefix="/api/people", tags=["people"])


class EnrollIn(BaseModel):
    device_id: str
    consent: bool
    samples: int = 10


class ConsentIn(BaseModel):
    kind: str = "face"
    granted: bool


class MergeIn(BaseModel):
    into: str


def _ext(c: Any) -> Any:
    ext = c.extensions.get("vision")
    if ext is None:
        raise Unavailable("identity not available")
    return ext


@router.get("")
async def people(_: User, c: C) -> list[dict[str, Any]]:
    return await _ext(c).identity.list()  # type: ignore[no-any-return]


@router.post("")
async def create(body: PersonIn, p: Admin, c: C) -> dict[str, str]:
    person = await _ext(c).identity.create(body)
    await c.audit.record(p.actor, "person.create", person.id)
    return {"id": person.id}


@router.patch("/{person_id}")
async def update(person_id: str, body: PersonPatch, p: Admin, c: C) -> dict[str, bool]:
    await _ext(c).identity.update(person_id, body)
    await c.audit.record(p.actor, "person.update", person_id)
    return {"ok": True}


@router.delete("/{person_id}")
async def delete(person_id: str, p: Admin, c: C) -> dict[str, bool]:
    await _ext(c).identity.delete(person_id)
    await c.audit.record(p.actor, "person.delete", person_id)
    return {"ok": True}


@router.post("/{person_id}/consent")
async def consent(person_id: str, body: ConsentIn, p: Admin, c: C) -> dict[str, bool]:
    await _ext(c).identity.set_consent(person_id, body.kind, body.granted,
                                       {"via": "admin", "user": p.username})
    await c.audit.record(p.actor, "person.consent", person_id, kind=body.kind, granted=body.granted)
    return {"ok": True}


@router.post("/{person_id}/enroll")
async def enroll(person_id: str, body: EnrollIn, p: Admin, c: C) -> dict[str, Any]:
    if not body.consent:
        raise ValidationFailed("consent required")
    ext = _ext(c)
    analyzer = ext.engine.faces
    if analyzer is None:
        raise Unavailable("no face analyzer installed")
    await ext.identity.set_consent(person_id, "face", True, {"via": "admin", "user": p.username})
    images = []
    for _ in range(min(body.samples, 20)):
        jpeg = await c.devices.snapshot(body.device_id, width=1920)
        img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if img is not None:
            images.append(img)
        await asyncio.sleep(0.35)
    result = await ext.identity.enroll_images(person_id, images, analyzer, source="admin")
    await c.audit.record(p.actor, "person.enroll", person_id, added=result.added)
    return result.__dict__  # type: ignore[no-any-return]


@router.get("/{person_id}/faces")
async def faces(person_id: str, _: Admin, c: C) -> list[dict[str, Any]]:
    return await _ext(c).identity.faces(person_id)  # type: ignore[no-any-return]


@router.get("/faces/{face_id}/thumbnail.jpg")
async def thumbnail(face_id: str, _: Admin, c: C) -> Response:
    return Response(await _ext(c).identity.face_thumbnail(face_id), media_type="image/jpeg",
                    headers={"Cache-Control": "no-store"})


@router.delete("/faces/{face_id}")
async def delete_face(face_id: str, p: Admin, c: C) -> dict[str, bool]:
    await _ext(c).identity.delete_face(face_id)
    await c.audit.record(p.actor, "person.face_delete", face_id)
    return {"ok": True}


@router.post("/{person_id}/merge")
async def merge(person_id: str, body: MergeIn, p: Admin, c: C) -> dict[str, bool]:
    await _ext(c).identity.merge(person_id, body.into)
    if c.memory is not None:
        await c.memory.service.merge_person(person_id, body.into)
    await c.audit.record(p.actor, "person.merge", person_id, into=body.into)
    return {"ok": True}


@router.get("/{person_id}/export")
async def export(person_id: str, p: Admin, c: C) -> dict[str, Any]:
    data: dict[str, Any] = await _ext(c).identity.export(person_id)
    if c.memory is not None:
        data["memories"] = [h.model_dump(mode="json") for h in
                            await c.memory.service.list_all(person_id=person_id, limit=5000)]
    await c.audit.record(p.actor, "person.export", person_id)
    return data
