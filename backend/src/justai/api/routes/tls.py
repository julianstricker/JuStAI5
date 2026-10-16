"""HTTPS for the device app: CA download, status, adding the address JuStAI5 is used under."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from justai.api.deps import Admin, C
from justai.common.errors import NotFound, ValidationFailed

router = APIRouter(prefix="/api/tls", tags=["tls"])


class NameIn(BaseModel):
    name: str


def _tls(request: Request) -> Any:
    tls = getattr(request.app.state, "tls", None)
    if tls is None:
        raise NotFound("https is disabled")
    return tls


@router.get("/ca.crt", include_in_schema=False)
async def ca_certificate(request: Request) -> Response:
    """Public on purpose: a device needs the CA before it can open the HTTPS page."""
    tls = _tls(request)
    return Response(tls.files.ca_cert.read_bytes(), media_type="application/x-x509-ca-cert",
                    headers={"Content-Disposition": 'attachment; filename="justai5-ca.crt"'})


@router.get("/status")
async def status(request: Request, _: Admin, c: C) -> dict[str, Any]:
    tls = getattr(request.app.state, "tls", None)
    if tls is None:
        return {"enabled": False}
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
    return {"enabled": True, "port": c.settings.https_port, "names": tls.names(),
            "ca_fingerprint": tls.ca_fingerprint(), "current_host": host,
            "current_host_covered": host.lower() in tls.names()}


@router.post("/names")
async def add_name(body: NameIn, request: Request, p: Admin, c: C) -> dict[str, Any]:
    tls = _tls(request)
    try:
        added = tls.add_name(body.name)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    await c.audit.record(p.actor, "tls.add_name", body.name)
    return {"added": added, "names": tls.names()}
