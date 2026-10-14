from __future__ import annotations

from typing import Any

from fastapi import APIRouter, UploadFile
from pydantic import BaseModel

from justai.api.deps import Admin, C
from justai.common.errors import ValidationFailed

router = APIRouter(prefix="/api/plugins", tags=["plugins"])

MAX_ARCHIVE = 20 * 1024 * 1024


class ConfigIn(BaseModel):
    config: dict[str, Any] = {}
    granted_permissions: list[str] | None = None


@router.get("")
async def list_plugins(_: Admin, c: C) -> list[dict[str, Any]]:
    return await c.plugins.list()


@router.post("/{plugin_id}/enable")
async def enable(plugin_id: str, p: Admin, c: C) -> dict[str, Any]:
    await c.plugins.enable(plugin_id)
    await c.audit.record(p.actor, "plugin.enable", plugin_id)
    row = await c.plugins.get_row(plugin_id)
    return {"status": row.status, "error": row.error}


@router.post("/{plugin_id}/disable")
async def disable(plugin_id: str, p: Admin, c: C) -> dict[str, bool]:
    await c.plugins.disable(plugin_id)
    await c.audit.record(p.actor, "plugin.disable", plugin_id)
    return {"ok": True}


@router.put("/{plugin_id}/config")
async def configure(plugin_id: str, body: ConfigIn, p: Admin, c: C) -> dict[str, bool]:
    await c.plugins.configure(plugin_id, body.config, body.granted_permissions)
    await c.audit.record(p.actor, "plugin.configure", plugin_id,
                         keys=sorted(body.config), permissions=body.granted_permissions)
    return {"ok": True}


@router.post("/install")
async def install(file: UploadFile, p: Admin, c: C) -> dict[str, Any]:
    data = await file.read(MAX_ARCHIVE + 1)
    if len(data) > MAX_ARCHIVE:
        raise ValidationFailed("archive too large")
    manifest = await c.plugins.install_archive(data)
    await c.audit.record(p.actor, "plugin.install", manifest.id, version=manifest.version)
    return {"id": manifest.id, "version": manifest.version, "permissions": manifest.permissions}


@router.delete("/{plugin_id}")
async def remove(plugin_id: str, p: Admin, c: C) -> dict[str, bool]:
    await c.plugins.remove(plugin_id)
    await c.audit.record(p.actor, "plugin.remove", plugin_id)
    return {"ok": True}
