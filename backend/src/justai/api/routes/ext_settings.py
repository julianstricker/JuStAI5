from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from justai.api.deps import Admin, C, User
from justai.devices.discovery import DiscoveryService
from justai.system.settings import SystemSettings

router = APIRouter(prefix="/api/settings", tags=["settings"])
admin_router = APIRouter(prefix="/api/discovery", tags=["discovery"])


class ScanIn(BaseModel):
    cidrs: list[str]


async def load(c: Any) -> SystemSettings:
    raw = await c.settings_store.get("system")
    settings = SystemSettings.model_validate(raw or {})
    if not settings.discovery_cidrs and c.settings.discovery_default_cidrs:
        settings.discovery_cidrs = list(c.settings.discovery_default_cidrs)
    return settings


@router.get("/system")
async def get_system(_: User, c: C) -> dict[str, Any]:
    return (await load(c)).model_dump()


@router.put("/system")
async def put_system(body: SystemSettings, p: Admin, c: C) -> dict[str, Any]:
    await c.settings_store.set("system", body)
    vision = c.extensions.get("vision")
    if vision is not None:
        vision.identity.store_thumbnails = body.store_face_thumbnails
    automation = c.extensions.get("automation")
    if automation is not None:
        await automation.engine.load_timezone()
    await c.audit.record(p.actor, "settings.system", None, discovery=body.discovery_cidrs)
    return body.model_dump()


@admin_router.get("/settings")
async def discovery_settings(_: Admin, c: C) -> dict[str, Any]:
    return {"cidrs": (await load(c)).discovery_cidrs}


@admin_router.post("/scan")
async def scan(body: ScanIn, p: Admin, c: C) -> list[dict[str, Any]]:
    settings = await load(c)
    # Ranges typed in the UI become authorised by the admin's explicit action.
    authorised = settings.discovery_cidrs or body.cidrs
    await c.audit.record(p.actor, "discovery.scan", None, cidrs=body.cidrs)
    return await DiscoveryService(c.providers, c.device_records).scan(body.cidrs, authorised)
