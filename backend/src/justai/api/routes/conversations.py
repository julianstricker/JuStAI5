from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from justai.api.deps import C, User
from justai.common.errors import Forbidden, NotFound

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class AskIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    room_id: str | None = None


@router.get("/active")
async def active(_: User, c: C) -> list[dict[str, Any]]:
    return [{"id": s.id, "endpoint_id": s.endpoint_id, "room_id": s.ctx.room_id,
             "room": s.ctx.room_name, "state": s.state.value, "mode": s.mode,
             "person": s.ctx.person_name, "language": s.ctx.language,
             "trigger": s.ctx.trigger, "user_turns": s.user_turns,
             "transcript": [{"role": t.role, "text": t.text, "t": t.t} for t in s.transcript][-20:]}
            for s in c.conversations.active()]


@router.get("/history")
async def history(_: User, c: C, limit: int = 50) -> list[dict[str, Any]]:
    return [{"id": r.id, "endpoint_id": r.endpoint_id, "room_id": r.room_id,
             "person_id": r.person_id, "trigger": r.trigger, "mode": r.mode,
             "language": r.language, "started_at": r.started_at, "ended_at": r.ended_at,
             "end_reason": r.end_reason} for r in await c.conversations.repo.list(limit)]


@router.get("/{session_id}/turns")
async def turns(session_id: str, _: User, c: C) -> list[dict[str, Any]]:
    return [{"role": t.role, "text": t.text, "created_at": t.created_at, "meta": t.meta}
            for t in await c.conversations.repo.turns(session_id)]


@router.post("/ask")
async def ask(body: AskIn, p: User, c: C) -> dict[str, Any]:
    """Text chat with the assistant (uses the same tools and memory as voice)."""
    session = c.conversations.get(body.session_id) if body.session_id else None
    if body.session_id and session is None:
        raise NotFound("session ended")
    if session is None:
        session = await c.conversations.start_text(room_id=body.room_id, user_role=p.role,
                                                   person_id=p.person_id)
    elif session.endpoint_id is not None and not p.is_admin:
        raise Forbidden("only admins can type into voice sessions")
    answer = await c.conversations.ask_text(session, body.text)
    return {"session_id": session.id, "answer": answer}


@router.post("/{session_id}/end")
async def end(session_id: str, _: User, c: C) -> dict[str, bool]:
    await c.conversations.end(session_id, "manual")
    return {"ok": True}
