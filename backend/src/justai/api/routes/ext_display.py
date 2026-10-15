from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import APIRouter, WebSocket
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from justai.api.deps import Admin, C, User
from justai.common.errors import Forbidden, Unavailable

router = APIRouter(prefix="/api/display", tags=["displays"])
admin_router = APIRouter(prefix="/api/displays", tags=["displays"])


class ApproveIn(BaseModel):
    name: str
    room_id: str | None = None


class PresentIn(BaseModel):
    document: dict[str, Any]


def _ext(c: Any) -> Any:
    ext = c.extensions.get("display")
    if ext is None:
        raise Unavailable("displays not available")
    return ext


@router.websocket("/ws")
async def display_ws(ws: WebSocket) -> None:
    """Endpoint for browser display clients (pairing + presentations)."""
    await ws.app.state.container.extensions["display"].service.handle_socket(ws)


@router.get("/camera/{device_id}.mp4")
async def camera(device_id: str, token: str, c: C) -> StreamingResponse:
    """Camera stream for a display, authorised by a short-lived signed token."""
    subject = c.auth.verify_scoped_token(token, "display-camera")
    if subject != device_id:
        raise Forbidden("token not valid for this camera")
    rt = c.devices.require(device_id)
    stream = rt.sub_stream or rt.stream
    if not stream:
        raise Unavailable("no stream")
    client = httpx.AsyncClient(base_url=c.settings.go2rtc_url, timeout=None)
    upstream = await client.send(client.build_request("GET", "/api/stream.mp4",
                                                      params={"src": stream, "video": "h264"}), stream=True)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(body(), media_type="video/mp4")


@admin_router.get("")
async def displays(_: User, c: C) -> list[dict[str, Any]]:
    return await _ext(c).service.list()  # type: ignore[no-any-return]


@admin_router.get("/pending")
async def pending(_: Admin, c: C) -> list[dict[str, Any]]:
    return _ext(c).service.pending_list()  # type: ignore[no-any-return]


@admin_router.post("/pairing/{code}/approve")
async def approve(code: str, body: ApproveIn, p: Admin, c: C) -> dict[str, str]:
    device_id = await _ext(c).service.approve(code, body.name, body.room_id)
    await c.audit.record(p.actor, "display.pair", device_id, room=body.room_id)
    return {"device_id": device_id}


@admin_router.get("/components")
async def components(_: User, c: C) -> list[dict[str, Any]]:
    return c.components.catalog()


@admin_router.get("/presentations")
async def presentations(_: User, c: C) -> list[dict[str, Any]]:
    return [{"id": p.id, "display_device_id": p.display_device_id, "room_id": p.room_id,
             "session_id": p.session_id, "status": p.status, "created_at": p.created_at,
             "displayed_at": p.displayed_at, "closed_at": p.closed_at, "error": p.error,
             "document": {"title": p.document.get("title")}} for p in await _ext(c).service.presentations()]


@admin_router.post("/{device_id}/present")
async def present(device_id: str, body: PresentIn, p: Admin, c: C) -> dict[str, Any]:
    rt = c.devices.get(device_id)
    pres = await _ext(c).service.present(body.document, target_room_id=rt.room_id if rt else None,
                                         target_device_id=device_id, system=True, source=p.actor)
    return {"id": pres.id, "status": pres.status, "error": pres.error}


@admin_router.post("/{device_id}/close/{presentation_id}")
async def close(device_id: str, presentation_id: str, _: Admin, c: C) -> dict[str, bool]:
    await _ext(c).service.close(device_id, presentation_id)
    return {"ok": True}
