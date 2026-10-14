from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from justai.api.deps import Admin, C, User
from justai.endpoints.service import EndpointIn, EndpointPatch, EndpointView

router = APIRouter(prefix="/api/endpoints", tags=["endpoints"])


class RecordIn(BaseModel):
    seconds: float = Field(10, ge=1, le=30)


def _view(c: Any, e: EndpointView) -> dict[str, Any]:
    data = e.model_dump(mode="json")
    audio = c.audio.endpoints.get(e.id)
    data["runtime"] = audio.stats() if audio else None
    session = c.conversations.for_endpoint(e.id)
    data["session"] = {"id": session.id, "state": session.state.value} if session else None
    return data


@router.get("")
async def list_endpoints(_: User, c: C) -> list[dict[str, Any]]:
    return [_view(c, e) for e in await c.endpoints.list()]


@router.get("/{endpoint_id}")
async def get_endpoint(endpoint_id: str, _: User, c: C) -> dict[str, Any]:
    return _view(c, await c.endpoints.get(endpoint_id))


@router.post("")
async def create_endpoint(body: EndpointIn, p: Admin, c: C) -> dict[str, Any]:
    ep = await c.endpoints.create(body)
    await c.audit.record(p.actor, "endpoint.create", ep.id)
    await c.refresh_topology()
    return _view(c, ep)


@router.patch("/{endpoint_id}")
async def update_endpoint(endpoint_id: str, body: EndpointPatch, p: Admin, c: C) -> dict[str, Any]:
    ep = await c.endpoints.update(endpoint_id, body)
    await c.audit.record(p.actor, "endpoint.update", endpoint_id)
    await c.refresh_topology()
    return _view(c, ep)


@router.delete("/{endpoint_id}")
async def delete_endpoint(endpoint_id: str, p: Admin, c: C) -> dict[str, bool]:
    await c.endpoints.delete(endpoint_id)
    await c.audit.record(p.actor, "endpoint.delete", endpoint_id)
    await c.refresh_topology()
    return {"ok": True}


@router.post("/{endpoint_id}/calibrate")
async def calibrate(endpoint_id: str, p: Admin, c: C) -> dict[str, Any]:
    """Measure the echo delay (plays three short chirps on the endpoint speaker)."""
    result = await c.audio.calibrate(endpoint_id)
    if result.get("delay_s") is not None:
        ep = await c.endpoints.get(endpoint_id)
        cfg = ep.config.model_copy(deep=True)
        cfg.audio.output_latency_ms = int(result["delay_s"] * 1000 + 150)
        await c.endpoints.update(endpoint_id, EndpointPatch(config=cfg))
        await c.refresh_topology()
    await c.audit.record(p.actor, "endpoint.calibrate", endpoint_id, **result)
    return result


@router.post("/{endpoint_id}/start-session")
async def start_session(endpoint_id: str, p: Admin, c: C) -> dict[str, str]:
    session = await c.conversations.start(endpoint_id, trigger="manual")
    return {"session_id": session.id}


@router.post("/{endpoint_id}/diagnostic-recording")
async def record(endpoint_id: str, body: RecordIn, p: Admin, c: C) -> Response:
    """Explicitly requested diagnostic recording; nothing is stored on the server."""
    await c.audit.record(p.actor, "audio.diagnostic_recording", endpoint_id, seconds=body.seconds)
    wav = await c.audio.record_diagnostics(endpoint_id, body.seconds)
    return Response(wav, media_type="audio/wav",
                    headers={"Content-Disposition": f'attachment; filename="{endpoint_id}.wav"'})


class SayIn(BaseModel):
    instruction: str = Field(min_length=1, max_length=1000)


@router.post("/{endpoint_id}/proactive")
async def proactive(endpoint_id: str, body: SayIn, p: Admin, c: C) -> dict[str, str]:
    """Start (or continue) a session with a system instruction, e.g. to test output."""
    session = await c.conversations.start(endpoint_id, trigger="manual", instruction=body.instruction)
    await c.audit.record(p.actor, "conversation.proactive", endpoint_id)
    return {"session_id": session.id}
