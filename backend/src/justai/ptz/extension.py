"""PTZ tools for the assistant."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from justai_sdk.permissions import Permission
from justai_sdk.ports.devices import Capability
from justai_sdk.tools import SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.common.errors import Unavailable
from justai.identity.service import IdentityService
from justai.ptz.service import PtzService
from justai.ptz.tracking import TrackingTarget
from justai.vision.extension import CameraTarget

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry

AMOUNTS = {"small": 0.15, "medium": 0.35, "large": 0.7}


class MoveParams(CameraTarget):
    direction: Literal["left", "right", "up", "down"]
    amount: Literal["small", "medium", "large"] = "medium"


class PresetParams(CameraTarget):
    preset: str = Field(description="Name des Presets")


class FollowParams(CameraTarget):
    target: str = Field("me", description="'me' (sprechende Person), 'person', ein Name oder eine "
                                          "Objektklasse wie 'dog'")


class SearchParams(CameraTarget):
    label: str = Field(description="Objektklasse (englisch), z. B. 'person', 'dog', 'car'")


class PtzExtension:
    def __init__(self, c: Container, service: PtzService, identity: IdentityService) -> None:
        self.c = c
        self.service = service
        self.identity = identity

    async def stop(self) -> None:
        await self.service.stop_all()

    async def _ptz_camera(self, target: CameraTarget, ctx: ToolContext) -> str:
        vision = self.c.extensions["vision"]
        device_id, room_id = await vision.resolve_camera(target, ctx)
        rt = self.c.devices.get(device_id)
        if rt is None or Capability.PTZ_PAN not in rt.capabilities:
            # Look for another PTZ camera in the same room.
            for other in self.c.devices.runtimes():
                if other.room_id == room_id and other.online and Capability.PTZ_PAN in other.capabilities:
                    return other.device_id
            raise Unavailable("in diesem Raum gibt es keine bewegliche Kamera")
        return device_id

    def register_tools(self, reg: ToolRegistry) -> None:
        svc = self.service

        async def move(p: MoveParams, ctx: ToolContext) -> ToolResult:
            device_id = await self._ptz_camera(p, ctx)
            amount = AMOUNTS[p.amount]
            pan = {"left": -amount, "right": amount}.get(p.direction, 0.0)
            tilt = {"up": amount, "down": -amount}.get(p.direction, 0.0)
            await svc.move(device_id, pan, tilt)
            return ToolResult.success(message="Kamera bewegt")

        reg.register(ToolDefinition(
            name="ptz.move", description="Schwenkt/neigt eine bewegliche Kamera.", parameters=MoveParams,
            category="ptz", side_effect=SideEffect.PHYSICAL, permissions=[Permission.CAMERA_PTZ]), move)

        async def preset(p: PresetParams, ctx: ToolContext) -> ToolResult:
            device_id = await self._ptz_camera(p, ctx)
            for pr in await svc.presets(device_id):
                if pr.name.lower() == p.preset.lower() or pr.id == p.preset:
                    await svc.goto_preset(device_id, pr.id)
                    return ToolResult.success(message=f"Preset {pr.name}")
            return ToolResult.failure("unknown_preset", f"Preset '{p.preset}' gibt es nicht")

        reg.register(ToolDefinition(
            name="ptz.goto_preset", description="Fährt eine gespeicherte Kameraposition an.",
            parameters=PresetParams, category="ptz", side_effect=SideEffect.PHYSICAL,
            permissions=[Permission.CAMERA_PTZ]), preset)

        async def home(p: CameraTarget, ctx: ToolContext) -> ToolResult:
            device_id = await self._ptz_camera(p, ctx)
            await svc.stop_tracking(device_id)
            await svc.home(device_id)
            return ToolResult.success(message="Ausgangsposition")

        reg.register(ToolDefinition(
            name="ptz.home", description="Kamera zurück in die Ausgangsposition (beendet Verfolgung).",
            parameters=CameraTarget, category="ptz", side_effect=SideEffect.PHYSICAL,
            permissions=[Permission.CAMERA_PTZ]), home)

        async def follow(p: FollowParams, ctx: ToolContext) -> ToolResult:
            device_id = await self._ptz_camera(p, ctx)
            value = p.target.strip().lower()
            if value in ("me", "mich", "mir", "self"):
                target = TrackingTarget("person_id", ctx.person_id) if ctx.person_id else TrackingTarget()
            elif value in ("person", "personen", "jemand"):
                target = TrackingTarget()
            else:
                person = await self.identity.find_by_name(p.target)
                if person is not None and person.kind == "person":
                    target = TrackingTarget("person_id", person.id)
                elif person is not None:  # a pet: follow its species, entity assignment by vision
                    target = TrackingTarget("label", person.species or value)
                else:
                    target = TrackingTarget("label", value)
            await svc.start_tracking(device_id, target)
            hint = " (größte sichtbare Person)" if target.kind == "person" else ""
            return ToolResult.success({"device_id": device_id, "target": target.value or target.kind},
                                      message="Ich folge jetzt mit der Kamera" + hint)

        reg.register(ToolDefinition(
            name="ptz.follow",
            description="Lässt eine bewegliche Kamera einer Person (z. B. 'me' = sprechende Person), einem "
                        "Haustier oder Objekt folgen. Manuelle Steuerung hat Vorrang.",
            parameters=FollowParams, category="ptz", side_effect=SideEffect.PHYSICAL,
            permissions=[Permission.CAMERA_PTZ, Permission.VISION_ANALYZE]), follow)

        async def stop_follow(p: CameraTarget, ctx: ToolContext) -> ToolResult:
            device_id = await self._ptz_camera(p, ctx)
            stopped = await svc.stop_tracking(device_id)
            return ToolResult.success(message="Verfolgung beendet" if stopped else "Es lief keine Verfolgung")

        reg.register(ToolDefinition(
            name="ptz.stop_follow", description="Beendet die Kameraverfolgung.", parameters=CameraTarget,
            category="ptz", side_effect=SideEffect.PHYSICAL, permissions=[Permission.CAMERA_PTZ]), stop_follow)

        async def search(p: SearchParams, ctx: ToolContext) -> ToolResult:
            device_id = await self._ptz_camera(p, ctx)
            result = await svc.scan(device_id, p.label)
            msg = (f"Gefunden bei: {', '.join(f['position'] for f in result['found'])}"
                   if result["found"] else f"Kein {p.label} gefunden ({len(result['visited'])} Blickrichtungen)")
            return ToolResult.success(result, message=msg)

        reg.register(ToolDefinition(
            name="vision.search_area",
            description="Sucht systematisch mit einer beweglichen Kamera nach etwas (z. B. 'ist jemand im "
                        "Garten?'), indem sie mehrere Blickrichtungen untersucht.",
            parameters=SearchParams, category="vision", side_effect=SideEffect.PHYSICAL, timeout_s=90,
            permissions=[Permission.CAMERA_PTZ, Permission.VISION_ANALYZE]), search)
