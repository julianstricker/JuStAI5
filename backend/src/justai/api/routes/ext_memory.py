from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from justai.api.deps import C, User
from justai.common.errors import Forbidden, Unavailable
from justai.memory.service import MemoryIn, MemoryPatch, MemoryService

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _svc(c: Any) -> MemoryService:
    ext = c.extensions.get("memory")
    if ext is None:
        raise Unavailable("memory not available")
    return ext.service  # type: ignore[no-any-return]


@router.get("")
async def list_memories(p: User, c: C, query: str = "", person_id: str | None = None,
                        kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    svc = _svc(c)
    if not p.is_admin and person_id not in (None, p.person_id):
        raise Forbidden("only admins can browse other people's memories")
    if query:
        scopes: tuple[str, ...] = ("private", "room", "shared", "system")
        hits = await svc.search(query, person_id=person_id if p.is_admin else p.person_id,
                                limit=limit, scopes=scopes, kind=kind, include_inactive=p.is_admin)
    elif p.is_admin:
        hits = await svc.list_all(person_id=person_id, kind=kind, limit=limit)
    else:
        hits = await svc.search("", person_id=p.person_id, limit=limit, kind=kind)
    return [h.model_dump(mode="json") for h in hits]


@router.post("")
async def create_memory(body: MemoryIn, p: User, c: C) -> dict[str, Any]:
    if not p.is_admin and body.owner_person_id not in (None, p.person_id):
        raise Forbidden("not allowed")
    hit = await _svc(c).add(body.model_copy(update={"source": {"type": "admin", "user": p.username}}))
    await c.audit.record(p.actor, "memory.create", hit.id)
    return hit.model_dump(mode="json")


@router.patch("/{memory_id}")
async def update_memory(memory_id: str, body: MemoryPatch, p: User, c: C) -> dict[str, Any]:
    svc = _svc(c)
    current = await svc.get(memory_id)
    if not p.is_admin and current.owner_person_id != p.person_id:
        raise Forbidden("not allowed")
    hit = await svc.update(memory_id, body)
    await c.audit.record(p.actor, "memory.update", memory_id)
    return hit.model_dump(mode="json")


@router.delete("/{memory_id}")
async def delete_memory(memory_id: str, p: User, c: C) -> dict[str, bool]:
    svc = _svc(c)
    current = await svc.get(memory_id)
    if not p.is_admin and current.owner_person_id != p.person_id:
        raise Forbidden("not allowed")
    await svc.delete(memory_id)
    await c.audit.record(p.actor, "memory.delete", memory_id)
    return {"ok": True}


@router.post("/consolidate")
async def consolidate(p: User, c: C) -> dict[str, int]:
    if not p.is_admin:
        raise Forbidden("admin only")
    return await _svc(c).consolidate()
