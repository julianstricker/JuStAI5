from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from justai.api.deps import Admin, C, User
from justai.automation.extension import describe_schema
from justai.common.errors import Unavailable

router = APIRouter(prefix="/api/automations", tags=["automations"])


class AutomationIn(BaseModel):
    name: str
    description: str = ""
    definition: dict[str, Any]
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    definition: dict[str, Any] | None = None
    enabled: bool | None = None


def _ext(c: Any) -> Any:
    ext = c.extensions.get("automation")
    if ext is None:
        raise Unavailable("automations not available")
    return ext


def _view(a: Any) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "description": a.description, "enabled": a.enabled,
            "definition": a.definition, "created_by": a.created_by, "owner_person_id": a.owner_person_id,
            "state": a.state, "revision": a.revision, "created_at": a.created_at, "updated_at": a.updated_at}


@router.get("/schema")
async def schema(_: User) -> dict[str, Any]:
    return describe_schema()


@router.get("")
async def list_automations(_: User, c: C) -> list[dict[str, Any]]:
    return [_view(a) for a in await _ext(c).service.list()]


@router.post("")
async def create(body: AutomationIn, p: Admin, c: C) -> dict[str, Any]:
    ext = _ext(c)
    auto = await ext.service.create_from_definition(name=body.name, description=body.description,
                                                    definition=body.definition, created_by=p.actor,
                                                    enabled=body.enabled)
    await ext.engine.reload()
    await c.audit.record(p.actor, "automation.create", auto.id)
    return _view(auto)


@router.patch("/{automation_id}")
async def update(automation_id: str, body: AutomationPatch, p: Admin, c: C) -> dict[str, Any]:
    ext = _ext(c)
    auto = await ext.service.update(automation_id, **body.model_dump(exclude_unset=True))
    await ext.engine.reload()
    await c.audit.record(p.actor, "automation.update", automation_id)
    return _view(auto)


@router.delete("/{automation_id}")
async def delete(automation_id: str, p: Admin, c: C) -> dict[str, bool]:
    ext = _ext(c)
    await ext.service.delete(automation_id)
    await ext.engine.reload()
    await c.audit.record(p.actor, "automation.delete", automation_id)
    return {"ok": True}


@router.post("/{automation_id}/run")
async def run(automation_id: str, p: Admin, c: C) -> dict[str, bool]:
    await _ext(c).engine.run_now(automation_id)
    await c.audit.record(p.actor, "automation.run", automation_id)
    return {"ok": True}


@router.get("/{automation_id}/runs")
async def runs(automation_id: str, _: User, c: C) -> list[dict[str, Any]]:
    return [{"id": r.id, "event_id": r.event_id, "status": r.status, "attempts": r.attempts,
             "started_at": r.started_at, "finished_at": r.finished_at, "error": r.error, "log": r.log}
            for r in await _ext(c).service.runs(automation_id)]
