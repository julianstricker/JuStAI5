"""API dependencies: container access, authentication, permission checks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request

from justai.auth.service import Principal
from justai.common.errors import Forbidden, Unauthorized
from justai.container import Container

COOKIE = "justai_session"
CSRF_HEADER = "x-justai"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def container(request: Request) -> Container:
    c: Container = request.app.state.container
    return c


async def principal(request: Request, c: Annotated[Container, Depends(container)]) -> Principal:
    token = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    elif COOKIE in request.cookies:
        token = request.cookies[COOKIE]
        # Cookie auth: state-changing requests must carry a custom header, which a
        # cross-site form cannot send without a CORS preflight (CSRF protection).
        if request.method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise Forbidden("missing CSRF header", code="csrf")
    if not token:
        raise Unauthorized("not authenticated")
    return await c.auth.authenticate(token)


def require(*permissions: str) -> Callable[..., Principal]:
    async def check(p: Annotated[Principal, Depends(principal)]) -> Principal:
        missing = [perm for perm in permissions if perm not in p.permissions]
        if missing:
            raise Forbidden(f"missing permission: {', '.join(missing)}")
        return p

    return check  # type: ignore[return-value]


def admin(p: Annotated[Principal, Depends(principal)]) -> Principal:
    if not p.is_admin:
        raise Forbidden("admin role required")
    return p


C = Annotated[Container, Depends(container)]
User = Annotated[Principal, Depends(principal)]
Admin = Annotated[Principal, Depends(admin)]
