"""Output Router: the single place that decides which devices may emit output.

Rules (deterministic, never delegated to the LLM):

1. Output goes to the room of the originating interaction (endpoint room wins over
   any room claimed elsewhere).
2. A different target room requires ``explicit_cross_room`` (set only by tools
   designed for announcements), the ``output.cross_room`` permission and a target
   room that accepts announcements.
3. An explicitly requested device must belong to the target room.
4. Audio prefers the speaker of the originating endpoint; fallback is another
   online speaker *of the same room* (never another room).
5. Personal content is not shown on displays in shared rooms unless allowed.
6. Offline devices are never selected; if nothing is available the request fails
   instead of silently using another room.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from justai_sdk.permissions import Permission
from justai_sdk.ports.devices import Capability

from justai.common.errors import RoutingDenied


class OutputKind(StrEnum):
    AUDIO = "audio"
    DISPLAY = "display"


@dataclass(frozen=True)
class TopoDevice:
    id: str
    name: str
    room_id: str | None
    capabilities: frozenset[str]
    online: bool
    preferred: bool = False


@dataclass(frozen=True)
class TopoEndpoint:
    id: str
    room_id: str
    speaker_id: str | None
    display_ids: tuple[str, ...]
    priority: int = 0
    enabled: bool = True


@dataclass(frozen=True)
class TopoRoom:
    id: str
    name: str
    shared_space: bool = True
    announcements_allowed: bool = True


class Topology(Protocol):
    def endpoint(self, endpoint_id: str) -> TopoEndpoint | None: ...

    def room(self, room_id: str) -> TopoRoom | None: ...

    def endpoints_in_room(self, room_id: str) -> list[TopoEndpoint]: ...

    def devices_in_room(self, room_id: str) -> list[TopoDevice]: ...

    def device(self, device_id: str) -> TopoDevice | None: ...


@dataclass(frozen=True)
class OutputRequest:
    kind: OutputKind
    origin_endpoint_id: str | None = None
    origin_room_id: str | None = None
    target_room_id: str | None = None
    target_device_id: str | None = None
    explicit_cross_room: bool = False
    permissions: frozenset[str] = frozenset()
    personal_content: bool = False
    allow_personal_on_shared: bool = False
    required_capabilities: frozenset[str] = frozenset()
    admin: bool = False  # admin UI test outputs may target any room explicitly


@dataclass(frozen=True)
class RouteDecision:
    kind: OutputKind
    room_id: str
    device_ids: tuple[str, ...]
    cross_room: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def device_id(self) -> str:
        return self.device_ids[0]


class OutputRouter:
    def __init__(self, topology: Topology) -> None:
        self.topology = topology

    def route(self, req: OutputRequest) -> RouteDecision:
        reasons: list[str] = []
        origin_room = self._origin_room(req, reasons)
        target_room = req.target_room_id or origin_room
        if target_room is None:
            raise RoutingDenied("output needs an originating room or an explicit target room")
        room = self.topology.room(target_room)
        if room is None:
            raise RoutingDenied(f"unknown room {target_room}")

        cross_room = origin_room is not None and target_room != origin_room
        if origin_room is None and not req.admin:
            raise RoutingDenied("output without an originating room is only allowed for admins")
        if cross_room:
            self._check_cross_room(req, room)
            reasons.append(f"explicit cross-room output to {room.name}")

        if req.target_device_id:
            device = self.topology.device(req.target_device_id)
            if device is None or device.room_id != target_room:
                raise RoutingDenied("the requested device is not in the target room")
            self._check_device(req, device, room)
            return RouteDecision(req.kind, target_room, (device.id,), cross_room,
                                 (*reasons, "explicit device"))

        if req.kind == OutputKind.AUDIO:
            ids = self._audio_candidates(req, target_room, cross_room, reasons)
        else:
            ids = self._display_candidates(req, room, cross_room, reasons)
        if not ids:
            raise RoutingDenied(f"no available {req.kind} output in room {room.name}")
        return RouteDecision(req.kind, target_room, tuple(ids), cross_room, tuple(reasons))

    # ------------------------------------------------------------------ helpers
    def _origin_room(self, req: OutputRequest, reasons: list[str]) -> str | None:
        if req.origin_endpoint_id:
            ep = self.topology.endpoint(req.origin_endpoint_id)
            if ep is None:
                raise RoutingDenied("unknown originating endpoint")
            if req.origin_room_id and req.origin_room_id != ep.room_id:
                reasons.append("origin room taken from endpoint")
            return ep.room_id
        return req.origin_room_id

    def _check_cross_room(self, req: OutputRequest, room: TopoRoom) -> None:
        if not req.explicit_cross_room:
            raise RoutingDenied(
                "output to another room requires an explicit cross-room request"
            )
        if Permission.OUTPUT_CROSS_ROOM not in req.permissions and not req.admin:
            raise RoutingDenied("missing permission output.cross_room")
        if not room.announcements_allowed:
            raise RoutingDenied(f"room {room.name} does not accept announcements")

    def _check_device(self, req: OutputRequest, device: TopoDevice, room: TopoRoom) -> None:
        if not device.online:
            raise RoutingDenied(f"device {device.name} is offline")
        needed = {Capability.AUDIO_OUTPUT} if req.kind == OutputKind.AUDIO else set(
            req.required_capabilities) or {Capability.DISPLAY_TEXT}
        if not needed <= device.capabilities:
            raise RoutingDenied(f"device {device.name} lacks {sorted(needed - device.capabilities)}")
        if req.kind == OutputKind.DISPLAY:
            self._check_privacy(req, room)

    def _check_privacy(self, req: OutputRequest, room: TopoRoom) -> None:
        if req.personal_content and room.shared_space and not req.allow_personal_on_shared:
            raise RoutingDenied(
                f"personal content may not be shown on shared displays in {room.name}",
                code="private_content_on_shared_display",
            )

    def _audio_candidates(self, req: OutputRequest, room_id: str, cross_room: bool,
                          reasons: list[str]) -> list[str]:
        ids: list[str] = []
        if not cross_room and req.origin_endpoint_id:
            ep = self.topology.endpoint(req.origin_endpoint_id)
            if ep and ep.speaker_id:
                speaker = self.topology.device(ep.speaker_id)
                if speaker and speaker.online and speaker.room_id in (None, room_id):
                    reasons.append("speaker of originating endpoint")
                    return [speaker.id]
                reasons.append("endpoint speaker unavailable, using same-room fallback")
        if cross_room:
            for ep in sorted(self.topology.endpoints_in_room(room_id), key=lambda e: -e.priority):
                speaker = self.topology.device(ep.speaker_id) if ep.speaker_id else None
                if ep.enabled and speaker and speaker.online:
                    reasons.append(f"speaker of endpoint {ep.id} in target room")
                    return [speaker.id]
        for device in self._sorted(self.topology.devices_in_room(room_id)):
            if device.online and Capability.AUDIO_OUTPUT in device.capabilities:
                ids.append(device.id)
        return ids[:1]

    def _display_candidates(self, req: OutputRequest, room: TopoRoom, cross_room: bool,
                            reasons: list[str]) -> list[str]:
        self._check_privacy(req, room)
        needed = set(req.required_capabilities) or {Capability.DISPLAY_TEXT}
        preferred: list[str] = []
        if not cross_room and req.origin_endpoint_id:
            ep = self.topology.endpoint(req.origin_endpoint_id)
            for did in ep.display_ids if ep else ():
                d = self.topology.device(did)
                if d and d.online and needed <= d.capabilities:
                    preferred.append(d.id)
        if preferred:
            reasons.append("display of originating endpoint")
            return preferred[:1]
        for device in self._sorted(self.topology.devices_in_room(room.id)):
            if device.online and needed <= device.capabilities:
                reasons.append("display in room")
                return [device.id]
        return []

    @staticmethod
    def _sorted(devices: list[TopoDevice]) -> list[TopoDevice]:
        return sorted(devices, key=lambda d: (not d.preferred, d.name))
