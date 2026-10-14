"""Reusable ONVIF PTZ controller (needs the ``onvif-zeep-async`` package).

Supports ContinuousMove, RelativeMove, AbsoluteMove, Stop, presets and home
position - each only if the camera advertises it.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from justai_sdk.ports.ptz import PtzCapabilities, PtzPosition, PtzPreset


class OnvifPtz:
    def __init__(self, host: str, port: int, username: str, password: str,
                 *, hfov_deg: float = 90.0, vfov_deg: float = 55.0) -> None:
        self.host, self.port = host, port
        self.username, self.password = username, password
        self._camera: Any = None
        self._ptz: Any = None
        self._profile: Any = None
        self._caps = PtzCapabilities(horizontal_fov_deg=hfov_deg, vertical_fov_deg=vfov_deg)
        self._lock = asyncio.Lock()

    async def connect(self) -> PtzCapabilities:
        from onvif import ONVIFCamera

        self._camera = ONVIFCamera(self.host, self.port, self.username, self.password)
        await self._camera.update_xaddrs()
        media = await self._camera.create_media_service()
        profiles = await media.GetProfiles()
        self._profile = next((p for p in profiles if getattr(p, "PTZConfiguration", None)), None)
        if self._profile is None:
            return self._caps
        self._ptz = await self._camera.create_ptz_service()
        node_token = self._profile.PTZConfiguration.NodeToken
        node = await self._ptz.GetNode({"NodeToken": node_token})
        spaces = node.SupportedPTZSpaces
        self._caps.pan = self._caps.tilt = True
        self._caps.continuous = bool(getattr(spaces, "ContinuousPanTiltVelocitySpace", None))
        self._caps.relative = bool(getattr(spaces, "RelativePanTiltTranslationSpace", None))
        self._caps.absolute = bool(getattr(spaces, "AbsolutePanTiltPositionSpace", None))
        self._caps.zoom = bool(getattr(spaces, "ContinuousZoomVelocitySpace", None))
        self._caps.presets = int(getattr(node, "MaximumNumberOfPresets", 0) or 0) > 0
        self._caps.home = bool(getattr(node, "HomeSupported", False))
        with contextlib.suppress(Exception):
            status = await self._ptz.GetStatus({"ProfileToken": self._profile.token})
            self._caps.position_feedback = status is not None and status.Position is not None
        return self._caps

    @property
    def ptz_capabilities(self) -> PtzCapabilities:
        return self._caps

    def _token(self) -> str:
        if self._ptz is None:
            raise RuntimeError("camera has no PTZ")
        return str(self._profile.token)

    async def continuous_move(self, pan_speed: float, tilt_speed: float, zoom_speed: float = 0.0,
                              duration_s: float = 0.5) -> None:
        async with self._lock:
            velocity: dict[str, Any] = {"PanTilt": {"x": max(-1, min(1, pan_speed)),
                                                    "y": max(-1, min(1, tilt_speed))}}
            if self._caps.zoom and zoom_speed:
                velocity["Zoom"] = {"x": zoom_speed}
            await self._ptz.ContinuousMove({"ProfileToken": self._token(), "Velocity": velocity})
            await asyncio.sleep(duration_s)
            await self._ptz.Stop({"ProfileToken": self._token(), "PanTilt": True, "Zoom": True})

    async def move_relative(self, pan_fov: float, tilt_fov: float, zoom: float = 0.0) -> None:
        if self._caps.relative:
            # Generic translation space is normalised to [-1, 1] for the full range.
            pan = pan_fov * self._caps.horizontal_fov_deg / (self._caps.pan_range_deg / 2)
            tilt = tilt_fov * self._caps.vertical_fov_deg / (self._caps.tilt_range_deg / 2)
            async with self._lock:
                await self._ptz.RelativeMove({"ProfileToken": self._token(), "Translation": {
                    "PanTilt": {"x": max(-1, min(1, pan)), "y": max(-1, min(1, tilt))}}})
            return
        # Fallback: short continuous move proportional to the requested distance.
        duration = min(1.5, 0.15 + 1.2 * max(abs(pan_fov), abs(tilt_fov)))
        await self.continuous_move(0.5 if pan_fov > 0 else -0.5 if pan_fov < 0 else 0.0,
                                   0.5 if tilt_fov > 0 else -0.5 if tilt_fov < 0 else 0.0,
                                   duration_s=duration)

    async def stop(self) -> None:
        if self._ptz is not None:
            await self._ptz.Stop({"ProfileToken": self._token(), "PanTilt": True, "Zoom": True})

    async def get_position(self) -> PtzPosition | None:
        if self._ptz is None:
            return None
        status = await self._ptz.GetStatus({"ProfileToken": self._token()})
        pos = getattr(status, "Position", None)
        if pos is None or pos.PanTilt is None:
            return None
        zoom = float(pos.Zoom.x) if getattr(pos, "Zoom", None) is not None else 0.0
        return PtzPosition(pan=float(pos.PanTilt.x), tilt=float(pos.PanTilt.y), zoom=zoom)

    async def move_absolute(self, position: PtzPosition) -> None:
        if not self._caps.absolute:
            raise NotImplementedError("camera does not support absolute positioning")
        await self._ptz.AbsoluteMove({"ProfileToken": self._token(), "Position": {
            "PanTilt": {"x": position.pan, "y": position.tilt}}})

    async def list_presets(self) -> list[PtzPreset]:
        if self._ptz is None:
            return []
        presets = await self._ptz.GetPresets({"ProfileToken": self._token()})
        return [PtzPreset(id=str(p.token), name=str(p.Name or p.token)) for p in presets or []]

    async def goto_preset(self, preset_id: str) -> None:
        await self._ptz.GotoPreset({"ProfileToken": self._token(), "PresetToken": preset_id})

    async def save_preset(self, name: str) -> PtzPreset:
        token = await self._ptz.SetPreset({"ProfileToken": self._token(), "PresetName": name})
        return PtzPreset(id=str(token), name=name)

    async def go_home(self) -> None:
        if self._caps.home:
            await self._ptz.GotoHomePosition({"ProfileToken": self._token()})
        else:
            presets = await self.list_presets()
            home = next((p for p in presets if p.name.lower() in ("home", "start", "default")), None)
            if home is None:
                raise NotImplementedError("no home position or 'home' preset")
            await self.goto_preset(home.id)
