"""Device driver port.

A *driver* knows how to talk to a class of devices (e.g. Tapo cameras). For each
configured device the core asks the driver to ``probe`` (detect real capabilities)
and ``open`` a :class:`DeviceHandle`. Capabilities are always reported by the
driver at runtime and never inferred from a model name alone.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

import numpy as np
from pydantic import BaseModel, Field

from justai_sdk.audio import AudioChunk
from justai_sdk.ports.display import DisplaySink
from justai_sdk.ports.ptz import PtzController


class Capability(StrEnum):
    VIDEO_INPUT = "video.input"
    AUDIO_INPUT = "audio.input"
    AUDIO_OUTPUT = "audio.output"
    AUDIO_FULL_DUPLEX = "audio.full_duplex"
    CAMERA_SNAPSHOT = "camera.snapshot"
    PTZ_PAN = "camera.ptz.pan"
    PTZ_TILT = "camera.ptz.tilt"
    PTZ_ZOOM = "camera.ptz.zoom"
    PTZ_PRESETS = "camera.ptz.presets"
    PTZ_ABSOLUTE = "camera.ptz.absolute"
    CAMERA_MOTION_EVENTS = "camera.motion_events"
    CAMERA_PRIVACY_MODE = "camera.privacy_mode"
    DISPLAY_TEXT = "display.text"
    DISPLAY_IMAGE = "display.image"
    DISPLAY_DASHBOARD = "display.dashboard"
    DISPLAY_VIDEO = "display.video"
    DISPLAY_INTERACTIVE = "display.interactive"
    DISPLAY_NOTIFICATIONS = "display.notifications"
    DISPLAY_FULLSCREEN = "display.fullscreen"
    SENSOR_MOTION = "sensor.motion"
    SENSOR_CONTACT = "sensor.contact"


class DeviceInfo(BaseModel):
    manufacturer: str | None = None
    model: str | None = None
    hardware_version: str | None = None
    firmware: str | None = None
    serial: str | None = None
    mac: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class Go2rtcMedia(BaseModel):
    """Media is relayed by go2rtc. The URLs are go2rtc *source* URLs (may hold secrets)."""

    sources: list[str]
    sub_sources: list[str] = Field(default_factory=list)  # low-res stream for analysis
    backchannel: bool = False  # go2rtc can play audio to the device
    backchannel_codec: str = "pcma"  # pcma | pcmu | opus | aac


class ProbeResult(BaseModel):
    ok: bool
    capabilities: list[str] = Field(default_factory=list)
    info: DeviceInfo = Field(default_factory=DeviceInfo)
    media: Go2rtcMedia | None = None
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class DeviceHealth(BaseModel):
    online: bool
    detail: str | None = None


@runtime_checkable
class AudioSource(Protocol):
    """Custom (non-go2rtc) microphone, yields chunks at ``sample_rate`` in real time."""

    sample_rate: int

    def stream(self) -> AsyncIterator[AudioChunk]: ...


@runtime_checkable
class AudioSink(Protocol):
    """Custom (non-go2rtc) speaker. ``write`` must not block longer than real time."""

    sample_rate: int

    async def write(self, chunk: AudioChunk) -> None: ...


@runtime_checkable
class VideoSource(Protocol):
    """Custom (non-go2rtc) camera producing BGR frames."""

    async def frame(self) -> np.ndarray | None: ...


class DeviceHandle(Protocol):
    device_id: str

    @property
    def capabilities(self) -> set[str]: ...

    def media(self) -> Go2rtcMedia | None: ...

    def audio_source(self) -> AudioSource | None: ...

    def audio_sink(self) -> AudioSink | None: ...

    def video_source(self) -> VideoSource | None: ...

    def ptz(self) -> PtzController | None: ...

    def display(self) -> DisplaySink | None: ...

    async def snapshot(self) -> bytes | None: ...

    async def health(self) -> DeviceHealth: ...

    async def close(self) -> None: ...


@runtime_checkable
class DeviceDriver(Protocol):
    driver_id: str
    display_name: str

    def config_schema(self) -> dict[str, Any]: ...

    def secret_fields(self) -> list[str]: ...

    async def probe(self, config: dict[str, Any]) -> ProbeResult: ...

    async def open(self, device_id: str, config: dict[str, Any], probe: ProbeResult) -> DeviceHandle: ...


class BaseDeviceHandle:
    """Convenience base class: override only what the device supports."""

    def __init__(self, device_id: str, capabilities: set[str]) -> None:
        self.device_id = device_id
        self._capabilities = set(capabilities)

    @property
    def capabilities(self) -> set[str]:
        return set(self._capabilities)

    def media(self) -> Go2rtcMedia | None:
        return None

    def audio_source(self) -> AudioSource | None:
        return None

    def audio_sink(self) -> AudioSink | None:
        return None

    def video_source(self) -> VideoSource | None:
        return None

    def ptz(self) -> PtzController | None:
        return None

    def display(self) -> DisplaySink | None:
        return None

    async def snapshot(self) -> bytes | None:
        return None

    async def health(self) -> DeviceHealth:
        return DeviceHealth(online=True)

    async def close(self) -> None:
        return None
