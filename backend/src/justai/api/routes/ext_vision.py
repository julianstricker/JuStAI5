from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter
from justai_sdk.ports.devices import Capability
from pydantic import BaseModel
from sqlalchemy import delete, select

from justai.api.deps import Admin, C, User
from justai.common.errors import Forbidden, Unavailable
from justai.db.models import Person, Sighting, VisionWatch
from justai.vision.engine import CameraVisionConfig

router = APIRouter(prefix="/api/vision", tags=["vision"])


class AnalyzeIn(BaseModel):
    device_id: str


class WatchIn(BaseModel):
    name: str
    camera_device_id: str
    labels: list[str]
    min_score: float = 0.5
    cooldown_s: float = 300
    zone: dict[str, Any] | None = None


def _ext(c: Any) -> Any:
    ext = c.extensions.get("vision")
    if ext is None:
        raise Unavailable("vision not available")
    return ext


@router.get("/labels")
async def labels(_: User, c: C) -> list[str]:
    return list(_ext(c).engine.labels())


@router.get("/cameras")
async def cameras(_: User, c: C) -> list[dict[str, Any]]:
    engine = _ext(c).engine
    out = []
    for d in await c.device_records.list():
        rt = c.devices.get(d.id)
        caps = rt.capabilities if rt and rt.online else set(d.capabilities)
        if Capability.VIDEO_INPUT not in caps:
            continue
        state = engine.cameras.get(d.id)
        out.append({"device_id": d.id, "name": d.name, "room_id": d.room_id,
                    "config": engine.config(d.id).model_dump(),
                    "active": d.id in engine.active_cameras(),
                    "stats": vars(state.stats) if state else None})
    return out


@router.put("/cameras/{device_id}")
async def set_camera(device_id: str, body: CameraVisionConfig, p: Admin, c: C) -> dict[str, Any]:
    await _ext(c).engine.set_config(device_id, body)
    await c.audit.record(p.actor, "vision.config", device_id, enabled=body.enabled, faces=body.faces,
                         zones=len(body.privacy_zones))
    return body.model_dump()


@router.post("/analyze")
async def analyze(body: AnalyzeIn, p: User, c: C) -> dict[str, Any]:
    if "camera.read" not in p.permissions:
        raise Forbidden("camera.read required")
    ext = _ext(c)
    result = await ext.engine.analyze_device(body.device_id)
    jpeg = ext.annotate(result["image_bgr"], result)
    return {
        "detections": [d.model_dump() for d in result["detections"]],
        "faces": [{"bbox": f["face"].bbox.model_dump(),
                   "person_name": f["match"].name if f["match"] else None,
                   "similarity": round(f["match"].similarity, 3) if f["match"] else None,
                   "match_level": f["match"].level if f["match"] else None,
                   "quality_issues": f["quality_issues"]} for f in result["faces"]],
        "image": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode(),
    }


@router.get("/sightings")
async def sightings(_: User, c: C, label: str | None = None, person_id: str | None = None,
                    limit: int = 100) -> list[dict[str, Any]]:
    stmt = select(Sighting).order_by(Sighting.last_seen.desc()).limit(min(limit, 500))
    if label:
        stmt = stmt.where(Sighting.label == label)
    if person_id:
        stmt = stmt.where(Sighting.person_id == person_id)
    async with c.db.session() as s:
        rows = (await s.scalars(stmt)).all()
        names = {p.id: p.name for p in (await s.scalars(select(Person))).all()}
    return [{"id": r.id, "camera_device_id": r.camera_device_id, "room_id": r.room_id, "label": r.label,
             "person_id": r.person_id, "person_name": names.get(r.person_id or ""),
             "first_seen": r.first_seen, "last_seen": r.last_seen, "best_score": r.best_score,
             "identity_similarity": r.identity_similarity} for r in rows]


@router.get("/watches")
async def watches(_: User, c: C) -> list[dict[str, Any]]:
    async with c.db.session() as s:
        rows = (await s.scalars(select(VisionWatch).order_by(VisionWatch.created_at.desc()))).all()
    return [{"id": w.id, "name": w.name, "camera_device_id": w.camera_device_id, "enabled": w.enabled,
             "spec": {k: v for k, v in (w.spec or {}).items() if k != "references"},
             "state": {k: v for k, v in (w.state or {}).items() if k in ("current", "since")},
             "created_by": w.created_by, "expires_at": w.expires_at} for w in rows]


@router.post("/watches")
async def create_watch(body: WatchIn, p: Admin, c: C) -> dict[str, str]:
    async with c.db.session() as s:
        w = VisionWatch(name=body.name, camera_device_id=body.camera_device_id, created_by=p.actor,
                        spec={"kind": "objects", "labels": body.labels, "min_score": body.min_score,
                              "cooldown_s": body.cooldown_s, "zone": body.zone})
        s.add(w)
        await s.flush()
        watch_id = w.id
    await _ext(c).engine.reload_watches()
    return {"id": watch_id}


@router.delete("/watches/{watch_id}")
async def delete_watch(watch_id: str, p: Admin, c: C) -> dict[str, bool]:
    async with c.db.session() as s:
        await s.execute(delete(VisionWatch).where(VisionWatch.id == watch_id))
    await _ext(c).engine.reload_watches()
    return {"ok": True}
