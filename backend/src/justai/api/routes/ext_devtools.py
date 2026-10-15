from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from justai.api.deps import Admin, C
from justai.common.errors import Unavailable

router = APIRouter(prefix="/api/devtools", tags=["devtools"])


class CreateIn(BaseModel):
    request: str = Field(min_length=5, max_length=2000)


class VersionIn(BaseModel):
    version: int


class FeedbackIn(BaseModel):
    feedback: str = Field(min_length=3, max_length=4000)


def _svc(c: Any) -> Any:
    ext = c.extensions.get("devtools")
    if ext is None:
        raise Unavailable("devtools not available")
    return ext.service


@router.get("/projects")
async def projects(_: Admin, c: C) -> list[dict[str, Any]]:
    return await _svc(c).list()  # type: ignore[no-any-return]


@router.post("/projects")
async def create(body: CreateIn, p: Admin, c: C) -> dict[str, str]:
    project_id = await _svc(c).create(body.request, {"user": p.username})
    await c.audit.record(p.actor, "devtools.create", project_id)
    return {"id": project_id}


@router.post("/projects/{project_id}/versions/{version}/approve")
async def approve(project_id: str, version: int, p: Admin, c: C) -> dict[str, bool]:
    await _svc(c).approve(project_id, version, p.actor)
    return {"ok": True}


@router.post("/projects/{project_id}/rollback")
async def rollback(project_id: str, body: VersionIn, p: Admin, c: C) -> dict[str, bool]:
    await _svc(c).rollback(project_id, body.version, p.actor)
    return {"ok": True}


@router.post("/projects/{project_id}/deactivate")
async def deactivate(project_id: str, p: Admin, c: C) -> dict[str, bool]:
    await _svc(c).deactivate(project_id, p.actor)
    return {"ok": True}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, p: Admin, c: C) -> dict[str, bool]:
    await _svc(c).delete(project_id, p.actor)
    return {"ok": True}


@router.post("/projects/{project_id}/revise")
async def revise(project_id: str, body: FeedbackIn, p: Admin, c: C) -> dict[str, bool]:
    await _svc(c).revise(project_id, body.feedback)
    await c.audit.record(p.actor, "devtools.revise", project_id)
    return {"ok": True}
