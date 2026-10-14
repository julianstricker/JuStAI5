"""Live topology snapshot for the Output Router.

Rooms/endpoints/devices come from the database (cached, refreshed on changes);
online state comes from the device runtime.
"""

from __future__ import annotations

from justai.devices.manager import DeviceManager
from justai.devices.service import DeviceService
from justai.endpoints.service import DeviceRole, EndpointService
from justai.output.router import TopoDevice, TopoEndpoint, TopoRoom
from justai.rooms.service import RoomService


class LiveTopology:
    def __init__(self, rooms: RoomService, endpoints: EndpointService, devices: DeviceService,
                 manager: DeviceManager) -> None:
        self._rooms_svc = rooms
        self._endpoints_svc = endpoints
        self._devices_svc = devices
        self._manager = manager
        self._rooms: dict[str, TopoRoom] = {}
        self._endpoints: dict[str, TopoEndpoint] = {}
        self._devices: dict[str, tuple[str, str | None, frozenset[str], bool]] = {}

    async def refresh(self) -> None:
        rooms = await self._rooms_svc.list()
        self._rooms = {
            r.id: TopoRoom(r.id, r.name,
                           shared_space=bool((r.policy or {}).get("shared_space", True)),
                           announcements_allowed=bool((r.policy or {}).get("announcements_allowed", True)))
            for r in rooms
        }
        self._endpoints = {
            e.id: TopoEndpoint(e.id, e.room_id, e.primary(DeviceRole.SPEAKER),
                               tuple(e.device_ids(DeviceRole.DISPLAY)), e.priority, e.enabled)
            for e in await self._endpoints_svc.list()
        }
        self._devices = {
            d.id: (d.name, d.room_id, frozenset(d.capabilities or []),
                   bool((d.settings or {}).get("preferred_output", False)))
            for d in await self._devices_svc.list()
            if d.enabled
        }

    def _topo_device(self, device_id: str) -> TopoDevice | None:
        row = self._devices.get(device_id)
        if row is None:
            return None
        name, room_id, caps, preferred = row
        runtime = self._manager.get(device_id)
        online = bool(runtime and runtime.online)
        if runtime and runtime.online:
            caps = frozenset(runtime.capabilities)
        return TopoDevice(device_id, name, room_id, caps, online, preferred)

    def endpoint(self, endpoint_id: str) -> TopoEndpoint | None:
        return self._endpoints.get(endpoint_id)

    def room(self, room_id: str) -> TopoRoom | None:
        return self._rooms.get(room_id)

    def endpoints_in_room(self, room_id: str) -> list[TopoEndpoint]:
        return [e for e in self._endpoints.values() if e.room_id == room_id]

    def devices_in_room(self, room_id: str) -> list[TopoDevice]:
        out = []
        for device_id, row in self._devices.items():
            if row[1] == room_id:
                d = self._topo_device(device_id)
                if d:
                    out.append(d)
        return out

    def device(self, device_id: str) -> TopoDevice | None:
        return self._topo_device(device_id)
