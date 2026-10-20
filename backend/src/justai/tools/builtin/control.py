"""Operating devices by voice: camera privacy mode, listening pause, reconnect, test tone,
image analysis on/off.

These are everyday operations a resident may do by voice (permission devices.control);
configuration (adding devices, drivers, credentials) stays in the admin interface.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from justai_sdk.permissions import Permission
from justai_sdk.ports.devices import Capability
from justai_sdk.tools import SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.endpoints.service import DeviceRole, EndpointPatch

if TYPE_CHECKING:
    from justai.container import Container
    from justai.devices.manager import DeviceRuntime

MAX_PAUSE_MIN = 24 * 60


class Target(BaseModel):
    device: str | None = Field(None, description="Device name or ID (optional)")
    room: str | None = Field(None, description="Room name or ID (default: room of the conversation)")


class PrivacyParams(Target):
    enabled: bool = Field(description="True = camera off (privacy mode), False = camera on again")
    everywhere: bool = Field(False, description="All cameras of the house (e.g. 'switch off all cameras')")


class ListeningParams(BaseModel):
    room: str | None = Field(None, description="Room name or ID (default: room of the conversation)")
    enabled: bool = Field(description="False = stop listening for the wakeword, True = listen again")
    minutes: int = Field(60, ge=1, le=MAX_PAUSE_MIN,
                         description="Pause length in minutes; listening resumes automatically afterwards")


class AnalysisParams(Target):
    enabled: bool = Field(description="True = analyse images of this camera, False = stop analysing")


async def _room_id(c: Container, room: str | None, ctx: ToolContext) -> str | None:
    if not room:
        return ctx.room_id
    found = await c.rooms.find(room)
    if found is None:
        raise LookupError(f"unknown room '{room}'")
    return str(found.id)


async def _devices(c: Container, target: Target, ctx: ToolContext, capability: str,
                   everywhere: bool = False) -> list[DeviceRuntime]:
    """Runtimes with the capability: the named device, else those of the room (or house)."""
    runtimes = [r for r in c.devices.runtimes() if capability in r.capabilities]
    if target.device:
        key = target.device.lower()
        hits = [r for r in runtimes if r.device_id == target.device or r.name.lower() == key]
        if not hits:
            hits = [r for r in runtimes if key in r.name.lower()]
        if not hits:
            raise LookupError(f"no device '{target.device}' with {capability}")
        return hits
    if everywhere:
        return runtimes
    room_id = await _room_id(c, target.room, ctx)
    if room_id is None:
        raise LookupError("no room given")
    hits = [r for r in runtimes if r.room_id == room_id]
    if not hits:
        raise LookupError(f"no device with {capability} in this room")
    return hits


def register(c: Container) -> None:
    reg = c.tools

    # ------------------------------------------------------------ privacy mode
    async def privacy(p: PrivacyParams, ctx: ToolContext) -> ToolResult:
        try:
            targets = await _devices(c, p, ctx, Capability.CAMERA_PRIVACY_MODE, p.everywhere)
        except LookupError as exc:
            return ToolResult.failure("not_found", str(exc))
        done, failed = [], []
        for rt in targets:
            control = getattr(rt.handle, "privacy", lambda: None)() if rt.handle else None
            if control is None:
                failed.append(f"{rt.name} (not connected)")
                continue
            try:
                await control.set(p.enabled)
                done.append(rt.name)
            except Exception as exc:
                failed.append(f"{rt.name} ({exc})")
        await c.audit.record("assistant", "device.privacy_mode", ",".join(done),
                             enabled=p.enabled, session=ctx.session_id)
        state = "off (privacy mode)" if p.enabled else "on"
        message = f"Cameras {state}: {', '.join(done) or 'none'}"
        if failed:
            message += f". Failed: {', '.join(failed)}"
        return ToolResult(ok=bool(done), data={"done": done, "failed": failed}, message=message,
                          error_code=None if done else "failed")

    reg.register(ToolDefinition(
        name="devices.privacy_mode",
        description="Switches cameras off (privacy mode: no image, no sound) or on again, e.g. "
                    "'switch off the camera in the living room', 'all cameras off', 'camera back on'.",
        parameters=PrivacyParams, category="devices", side_effect=SideEffect.PHYSICAL,
        permissions=[Permission.DEVICES_CONTROL]), privacy)

    # -------------------------------------------------------- listening pause
    async def listening(p: ListeningParams, ctx: ToolContext) -> ToolResult:
        try:
            room_id = await _room_id(c, p.room, ctx)
        except LookupError as exc:
            return ToolResult.failure("not_found", str(exc))
        endpoints = [e for e in await c.endpoints.list() if e.room_id == room_id and e.primary(DeviceRole.MIC)]
        if not endpoints:
            return ToolResult.failure("not_found", "no listening endpoint in this room")
        for ep in endpoints:
            config = ep.config.model_copy(deep=True)
            config.wakeword.enabled = p.enabled
            await c.endpoints.update(ep.id, EndpointPatch(config=config))
        await c.refresh_topology()
        names = ", ".join(e.name for e in endpoints)
        await c.audit.record("assistant", "endpoint.listening", names, enabled=p.enabled,
                             minutes=None if p.enabled else p.minutes, session=ctx.session_id)
        if p.enabled:
            return ToolResult.success({"endpoints": names}, message=f"Listening again: {names}")
        until = await _schedule_resume(c, room_id, p.minutes, ctx)
        return ToolResult.success({"endpoints": names, "until": until},
                                  message=f"Not listening for the wakeword until {until}: {names}")

    reg.register(ToolDefinition(
        name="audio.listening",
        description="Pauses listening for the wakeword in a room for some minutes (privacy), "
                    "e.g. 'stop listening in the bedroom for an hour', or resumes it. Listening "
                    "resumes automatically after the pause.",
        parameters=ListeningParams, category="audio", side_effect=SideEffect.WRITE,
        permissions=[Permission.DEVICES_CONTROL]), listening)

    # ---------------------------------------------------------------- reconnect
    async def reconnect(p: Target, ctx: ToolContext) -> ToolResult:
        try:
            room_id = await _room_id(c, p.room, ctx)
        except LookupError as exc:
            return ToolResult.failure("not_found", str(exc))
        runtimes = c.devices.runtimes()
        if p.device:
            key = p.device.lower()
            targets = [r for r in runtimes if r.device_id == p.device or key in r.name.lower()]
        else:
            targets = [r for r in runtimes if r.room_id == room_id]
        if not targets:
            return ToolResult.failure("not_found", "no matching device")
        for rt in targets:
            await c.devices.reload(rt.device_id)
        await c.refresh_topology()
        return ToolResult.success({"devices": [r.name for r in targets]},
                                  message="Reconnecting: " + ", ".join(r.name for r in targets))

    reg.register(ToolDefinition(
        name="devices.reconnect",
        description="Reconnects a device (or all devices of a room), e.g. when a camera hangs or "
                    "no sound comes. Takes a few seconds; the device is briefly unavailable.",
        parameters=Target, category="devices", side_effect=SideEffect.PHYSICAL,
        permissions=[Permission.DEVICES_CONTROL]), reconnect)

    # ---------------------------------------------------------------- test tone
    async def test_tone(p: Target, ctx: ToolContext) -> ToolResult:
        try:
            targets = await _devices(c, p, ctx, Capability.AUDIO_OUTPUT)
        except LookupError as exc:
            return ToolResult.failure("not_found", str(exc))
        played = []
        for rt in targets:
            try:
                await c.audio.play_test_tone(rt.device_id)
                played.append(rt.name)
            except Exception as exc:
                return ToolResult.failure("failed", f"{rt.name}: {exc}")
        return ToolResult.success({"devices": played}, message="Test tone played: " + ", ".join(played))

    reg.register(ToolDefinition(
        name="devices.test_speaker",
        description="Plays a short test tone on a speaker (e.g. 'test the speaker in the kitchen').",
        parameters=Target, category="devices", side_effect=SideEffect.PHYSICAL, timeout_s=45,
        permissions=[Permission.DEVICES_CONTROL, Permission.SPEAKER_WRITE]), test_tone)

    # ----------------------------------------------------------- image analysis
    async def analysis(p: AnalysisParams, ctx: ToolContext) -> ToolResult:
        vision = c.extensions.get("vision")
        if vision is None:
            return ToolResult.failure("unavailable", "image analysis is not available")
        try:
            targets = await _devices(c, p, ctx, Capability.VIDEO_INPUT)
        except LookupError as exc:
            return ToolResult.failure("not_found", str(exc))
        for rt in targets:
            cfg = vision.engine.config(rt.device_id).model_copy()
            cfg.enabled = p.enabled
            await vision.engine.set_config(rt.device_id, cfg)
        await c.audit.record("assistant", "vision.config", ",".join(r.name for r in targets),
                             enabled=p.enabled, session=ctx.session_id)
        state = "on" if p.enabled else "off"
        return ToolResult.success({"cameras": [r.name for r in targets]},
                                  message=f"Image analysis {state}: " + ", ".join(r.name for r in targets))

    reg.register(ToolDefinition(
        name="vision.analysis",
        description="Switches the local image analysis (people, faces, objects) of a camera on or "
                    "off, e.g. 'stop analysing the living room camera'. The camera keeps running.",
        parameters=AnalysisParams, category="vision", side_effect=SideEffect.WRITE,
        permissions=[Permission.VISION_MANAGE]), analysis)


async def _schedule_resume(c: Container, room_id: str | None, minutes: int, ctx: ToolContext) -> str:
    """A one-time automation turns listening back on (survives restarts)."""
    from justai.system.settings import SystemSettings

    raw = await c.settings_store.get("system", {})
    tz = ZoneInfo(SystemSettings.model_validate(raw or {}).timezone)
    at = datetime.now(tz) + timedelta(minutes=minutes)
    automation = c.extensions.get("automation")
    if automation is not None:
        definition: dict[str, Any] = {
            "trigger": {"type": "at", "at": at.replace(tzinfo=None).isoformat(timespec="seconds")},
            "actions": [{"type": "tool", "name": "audio.listening",
                         "args": {"room": room_id, "enabled": True}}]}
        await automation.service.create_from_definition(
            name=f"Listening pause ends ({minutes} min)", description="audio.listening",
            definition=definition, created_by="assistant", owner_person_id=ctx.person_id,
            origin={"session_id": ctx.session_id})
        await automation.engine.reload()
    return at.strftime("%H:%M")
