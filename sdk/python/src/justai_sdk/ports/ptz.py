"""Vendor-neutral PTZ port.

Coordinates are normalised: pan/tilt in ``[-1, 1]`` of the mechanical range,
zoom in ``[0, 1]``. Relative moves are expressed as a fraction of the current
field of view, which is what visual tracking needs ("the target is 0.2 FOV to the
right").
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class PtzCapabilities(BaseModel):
    pan: bool = False
    tilt: bool = False
    zoom: bool = False
    relative: bool = False
    continuous: bool = False
    absolute: bool = False
    presets: bool = False
    home: bool = False
    position_feedback: bool = False
    # Approximate field of view, used to convert image offsets into movements.
    horizontal_fov_deg: float = 90.0
    vertical_fov_deg: float = 55.0
    # Mechanical range in degrees (for converting FOV fractions into range fractions).
    pan_range_deg: float = 360.0
    tilt_range_deg: float = 120.0


class PtzPosition(BaseModel):
    pan: float
    tilt: float
    zoom: float = 0.0


class PtzPreset(BaseModel):
    id: str
    name: str


@runtime_checkable
class PtzController(Protocol):
    @property
    def ptz_capabilities(self) -> PtzCapabilities: ...

    async def move_relative(self, pan_fov: float, tilt_fov: float, zoom: float = 0.0) -> None:
        """Move by a fraction of the field of view (positive = right / up / zoom in)."""
        ...

    async def continuous_move(
        self, pan_speed: float, tilt_speed: float, zoom_speed: float = 0.0, duration_s: float = 0.5
    ) -> None: ...

    async def stop(self) -> None: ...

    async def get_position(self) -> PtzPosition | None: ...

    async def move_absolute(self, position: PtzPosition) -> None: ...

    async def list_presets(self) -> list[PtzPreset]: ...

    async def goto_preset(self, preset_id: str) -> None: ...

    async def save_preset(self, name: str) -> PtzPreset: ...

    async def go_home(self) -> None: ...
