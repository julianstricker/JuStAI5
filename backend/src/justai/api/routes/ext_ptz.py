from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from justai.api.deps import C, User
from justai.common.errors import Forbidden, Unavailable
from justai.ptz.tracking import TrackingTarget

router = APIRouter(prefix="/api/ptz", tags=["ptz"])


class MoveIn(BaseModel):
    pan: float = Field(0.0, ge=-1, le=1)
    tilt: float = Field(0.0, ge=-1, le=1)
    zoom: float = Field(0.0, ge=-1, le=1)


class TrackIn(BaseModel):
    enable: bool
    target: str = "person"  # person | label:<name> | person_id:<id>


class PresetIn(BaseModel):
    name: str


def _svc(c: Any, p: Any) -> Any:
    if "camera.ptz" not in p.permissions:
        raise Forbidden("camera.ptz required")
    ext = c.extensions.get("ptz")
    if ext is None:
        raise Unavailable("ptz not available")
    return ext.service


@router.get("/{device_id}/status")
async def status(device_id: str, p: User, c: C) -> dict[str, Any]:
    return _svc(c, p).status(device_id)  # type: ignore[no-any-return]


@router.post("/{device_id}/move")
async def move(device_id: str, body: MoveIn, p: User, c: C) -> dict[str, bool]:
    await _svc(c, p).move(device_id, body.pan, body.tilt, body.zoom, manual=True)
    return {"ok": True}


@router.post("/{device_id}/stop")
async def stop(device_id: str, p: User, c: C) -> dict[str, bool]:
    await _svc(c, p).stop(device_id)
    return {"ok": True}


@router.post("/{device_id}/home")
async def home(device_id: str, p: User, c: C) -> dict[str, bool]:
    await _svc(c, p).home(device_id)
    return {"ok": True}


@router.get("/{device_id}/presets")
async def presets(device_id: str, p: User, c: C) -> list[dict[str, str]]:
    return [pr.model_dump() for pr in await _svc(c, p).presets(device_id)]


@router.post("/{device_id}/presets")
async def save_preset(device_id: str, body: PresetIn, p: User, c: C) -> dict[str, str]:
    return (await _svc(c, p).save_preset(device_id, body.name)).model_dump()  # type: ignore[no-any-return]


@router.post("/{device_id}/presets/{preset_id}/goto")
async def goto(device_id: str, preset_id: str, p: User, c: C) -> dict[str, bool]:
    await _svc(c, p).goto_preset(device_id, preset_id)
    return {"ok": True}


@router.post("/{device_id}/track")
async def track(device_id: str, body: TrackIn, p: User, c: C) -> dict[str, bool]:
    svc = _svc(c, p)
    if not body.enable:
        await svc.stop_tracking(device_id)
        return {"ok": True}
    kind, _, value = body.target.partition(":")
    target = TrackingTarget() if kind == "person" else TrackingTarget(kind, value or None)
    await svc.start_tracking(device_id, target)
    await c.audit.record(p.actor, "ptz.track", device_id, tracking_target=body.target)
    return {"ok": True}
