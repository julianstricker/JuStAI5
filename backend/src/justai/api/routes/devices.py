from __future__ import annotations

from typing import Any

import httpx
import jsonschema
from fastapi import APIRouter, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from justai.api.deps import Admin, C, User
from justai.common.errors import NotFound, Unavailable, ValidationFailed
from justai.devices.service import DeviceIn, DevicePatch

router = APIRouter(prefix="/api/devices", tags=["devices"])


class ProbeIn(BaseModel):
    driver_id: str
    config: dict[str, Any]


def _driver_secret_fields(c: Any, driver_id: str) -> list[str]:
    driver = c.devices.driver(driver_id)
    return list(driver.secret_fields()) if driver else []


async def _device(c: Any, d: Any) -> dict[str, Any]:
    rt = c.devices.get(d.id)
    return {
        "id": d.id, "name": d.name, "driver_id": d.driver_id, "room_id": d.room_id,
        "enabled": d.enabled, "config": d.config, "settings": d.settings,
        "secret_fields_set": await c.device_records.secret_fields_present(d.id),
        "capabilities": sorted(rt.capabilities) if rt and rt.online else d.capabilities,
        "info": d.info, "status": rt.status if rt else d.status,
        "status_detail": rt.detail if rt else d.status_detail,
        "last_seen_at": d.last_seen_at, "stream": rt.stream if rt else None,
        "audio": {"input": d.id in c.audio.mics, "output": d.id in c.audio.speakers},
    }


@router.get("/drivers")
async def drivers(_: User, c: C) -> list[dict[str, Any]]:
    out = []
    for entry in c.providers.entries("device_driver"):
        drv = entry.provider
        out.append({"id": entry.id, "name": drv.display_name, "plugin_id": entry.plugin_id,
                    "config_schema": drv.config_schema(), "secret_fields": drv.secret_fields()})
    return out


@router.get("")
async def list_devices(_: User, c: C, room_id: str | None = None) -> list[dict[str, Any]]:
    return [await _device(c, d) for d in await c.device_records.list(room_id=room_id)]


@router.get("/{device_id}")
async def get_device(device_id: str, _: User, c: C) -> dict[str, Any]:
    return await _device(c, await c.device_records.get(device_id))


def _validate_config(c: Any, driver_id: str, config: dict[str, Any], partial: bool) -> None:
    driver = c.devices.driver(driver_id)
    if driver is None:
        raise ValidationFailed(f"driver {driver_id} not available")
    schema = dict(driver.config_schema())
    if partial:
        schema.pop("required", None)
    try:
        jsonschema.validate(config, schema)
    except jsonschema.ValidationError as exc:
        raise ValidationFailed(f"invalid device config: {exc.message}") from exc


@router.post("")
async def create_device(body: DeviceIn, p: Admin, c: C) -> dict[str, Any]:
    _validate_config(c, body.driver_id, body.config, partial=False)
    device = await c.device_records.create(body, _driver_secret_fields(c, body.driver_id))
    await c.audit.record(p.actor, "device.create", device.id, driver=body.driver_id)
    if device.enabled:
        await c.devices.activate(device)
    await c.refresh_topology()
    return await _device(c, device)


@router.patch("/{device_id}")
async def update_device(device_id: str, body: DevicePatch, p: Admin, c: C) -> dict[str, Any]:
    current = await c.device_records.get(device_id)
    if body.config is not None:
        _validate_config(c, current.driver_id, body.config, partial=True)
    device = await c.device_records.update(device_id, body,
                                           _driver_secret_fields(c, current.driver_id))
    await c.audit.record(p.actor, "device.update", device_id,
                         fields=sorted(body.model_dump(exclude_none=True)))
    await c.devices.reload(device_id)
    await c.refresh_topology()
    return await _device(c, device)


@router.delete("/{device_id}")
async def delete_device(device_id: str, p: Admin, c: C) -> dict[str, bool]:
    await c.devices.deactivate(device_id)
    await c.device_records.delete(device_id)
    await c.audit.record(p.actor, "device.delete", device_id)
    await c.refresh_topology()
    return {"ok": True}


@router.post("/probe")
async def probe(body: ProbeIn, _: Admin, c: C) -> dict[str, Any]:
    """Test a connection with the given config without saving it."""
    result = await c.devices.probe(body.driver_id, body.config)
    return result.model_dump(exclude={"media"})


@router.post("/{device_id}/reconnect")
async def reconnect(device_id: str, _: Admin, c: C) -> dict[str, bool]:
    await c.devices.reload(device_id)
    return {"ok": True}


@router.get("/{device_id}/snapshot.jpg")
async def snapshot(device_id: str, p: User, c: C, width: int = 960) -> Response:
    if "camera.read" not in p.permissions:
        raise NotFound("not allowed")
    data = await c.devices.snapshot(device_id, width=width)
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/{device_id}/live.mp4")
async def live(device_id: str, p: User, c: C) -> StreamingResponse:
    """Live preview (fragmented MP4, H.264) proxied from go2rtc - go2rtc stays internal."""
    if "camera.read" not in p.permissions:
        raise NotFound("not allowed")
    rt = c.devices.require(device_id)
    stream = rt.sub_stream or rt.stream
    if not stream:
        raise Unavailable("device has no video stream")
    client = httpx.AsyncClient(base_url=c.settings.go2rtc_url, timeout=None)
    req = client.build_request("GET", "/api/stream.mp4", params={"src": stream, "video": "h264"})
    upstream = await client.send(req, stream=True)

    async def body():  # type: ignore[no-untyped-def]
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    await c.audit.record(p.actor, "camera.live_view", device_id)
    return StreamingResponse(body(), media_type="video/mp4", headers={"Cache-Control": "no-store"})


@router.post("/{device_id}/test-tone")
async def test_tone(device_id: str, _: Admin, c: C) -> dict[str, bool]:
    await c.audio.play_test_tone(device_id)
    return {"ok": True}
