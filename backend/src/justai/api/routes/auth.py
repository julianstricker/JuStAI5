from __future__ import annotations

from fastapi import APIRouter, Response
from pydantic import BaseModel, Field

from justai.api.deps import COOKIE, Admin, C, User
from justai.auth.rbac import Role

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8)
    role: Role = Role.RESIDENT
    display_name: str = ""
    person_id: str | None = None


class UserPatch(BaseModel):
    role: Role | None = None
    display_name: str | None = None
    disabled: bool | None = None
    password: str | None = Field(None, min_length=8)
    person_id: str | None = None


@router.post("/login")
async def login(body: LoginIn, response: Response, c: C) -> dict[str, object]:
    token, p = await c.auth.login(body.username, body.password)
    response.set_cookie(COOKIE, token, httponly=True, samesite="strict",
                        secure=c.settings.public_url.startswith("https"),
                        max_age=c.settings.jwt_ttl_hours * 3600)
    await c.audit.record(p.actor, "auth.login")
    return {"token": token, "user": {"id": p.user_id, "username": p.username, "role": p.role}}


@router.post("/logout")
async def logout(response: Response, p: User) -> dict[str, bool]:
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.post("/logout-all")
async def logout_all(response: Response, p: User, c: C) -> dict[str, bool]:
    await c.auth.logout_everywhere(p.user_id)
    response.delete_cookie(COOKIE)
    return {"ok": True}


@router.get("/me")
async def me(p: User) -> dict[str, object]:
    return {"id": p.user_id, "username": p.username, "role": p.role,
            "permissions": sorted(p.permissions), "person_id": p.person_id}


@router.get("/users")
async def users(_: Admin, c: C) -> list[dict[str, object]]:
    return [{"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role,
             "disabled": u.disabled, "person_id": u.person_id,
             "last_login_at": u.last_login_at} for u in await c.auth.list_users()]


@router.post("/users")
async def create_user(body: UserIn, p: Admin, c: C) -> dict[str, str]:
    user = await c.auth.create_user(body.username, body.password, body.role, body.display_name,
                                    body.person_id)
    await c.audit.record(p.actor, "user.create", user.username, role=body.role)
    return {"id": user.id}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, p: Admin, c: C) -> dict[str, bool]:
    await c.auth.update_user(user_id, role=body.role, display_name=body.display_name,
                             disabled=body.disabled, password=body.password,
                             person_id=body.person_id)
    await c.audit.record(p.actor, "user.update", user_id,
                         fields=sorted(body.model_dump(exclude_none=True)))
    return {"ok": True}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, p: Admin, c: C) -> dict[str, bool]:
    if user_id == p.user_id:
        from justai.common.errors import Conflict

        raise Conflict("you cannot delete yourself")
    await c.auth.delete_user(user_id)
    await c.audit.record(p.actor, "user.delete", user_id)
    return {"ok": True}
