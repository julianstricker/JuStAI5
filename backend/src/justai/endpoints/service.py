"""Interaction endpoints: a concrete place to talk to the assistant.

An endpoint combines independent devices (e.g. Tapo camera as video input, USB mic
as audio input, network speaker as output, TV as display) into one communication
point with its own wakeword and audio configuration.
"""

from __future__ import annotations

import builtins
from enum import StrEnum

from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from justai.common.errors import NotFound, ValidationFailed
from justai.db.engine import Database
from justai.db.models import Device, EndpointDevice, InteractionEndpoint


class DeviceRole(StrEnum):
    MIC = "mic"
    CAMERA = "camera"
    SPEAKER = "speaker"
    DISPLAY = "display"


class DuplexMode(StrEnum):
    AUTO = "auto"
    FULL = "full"
    HALF = "half"


class ConversationMode(StrEnum):
    DEFAULT = "default"  # use the global AI setting
    REALTIME = "realtime"
    PIPELINE = "pipeline"


class WakewordConfig(BaseModel):
    enabled: bool = True
    models: list[str] = Field(default_factory=lambda: ["hey_jarvis"])
    threshold: float = Field(0.5, ge=0.05, le=0.99)
    # Score needed while the assistant itself is speaking (full duplex only).
    threshold_during_playback: float = Field(0.85, ge=0.05, le=0.999)


class AudioConfig(BaseModel):
    duplex: DuplexMode = DuplexMode.AUTO
    aec: bool = True
    noise_suppression: bool = True
    # Output latency (emission -> audible -> back in the mic). Measured by calibration.
    output_latency_ms: int | None = None
    echo_tail_ms: int = 600
    input_gain_db: float = 0.0
    vad_threshold: float = Field(0.5, ge=0.1, le=0.95)
    barge_in: bool = True
    barge_in_min_speech_ms: int = 300


class EndpointConversationConfig(BaseModel):
    mode: ConversationMode = ConversationMode.DEFAULT
    inactivity_timeout_s: float = Field(10.0, ge=3.0, le=300.0)
    end_of_utterance_silence_ms: int = Field(700, ge=200, le=3000)
    max_utterance_s: float = 30.0
    voice: str | None = None
    default_role: str = "resident"  # permissions of anonymous speakers here
    follow_up_listening: bool = True
    send_video: bool = False  # stream camera frames to realtime providers that support it


class EndpointConfig(BaseModel):
    wakeword: WakewordConfig = Field(default_factory=WakewordConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    conversation: EndpointConversationConfig = Field(default_factory=EndpointConversationConfig)


class EndpointDeviceRef(BaseModel):
    device_id: str
    role: DeviceRole
    priority: int = 0


class EndpointIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    room_id: str
    enabled: bool = True
    priority: int = 0
    arbitration_group: str = "default"
    language: str | None = None
    config: EndpointConfig = Field(default_factory=EndpointConfig)
    devices: list[EndpointDeviceRef] = Field(default_factory=list)


class EndpointPatch(BaseModel):
    name: str | None = None
    room_id: str | None = None
    enabled: bool | None = None
    priority: int | None = None
    arbitration_group: str | None = None
    language: str | None = None
    config: EndpointConfig | None = None
    devices: list[EndpointDeviceRef] | None = None


class EndpointView(BaseModel):
    """Resolved endpoint used by the runtime."""

    id: str
    name: str
    room_id: str
    enabled: bool
    priority: int
    arbitration_group: str
    language: str | None
    config: EndpointConfig
    devices: list[EndpointDeviceRef]

    def device_ids(self, role: DeviceRole) -> list[str]:
        refs = sorted((d for d in self.devices if d.role == role), key=lambda d: -d.priority)
        return [d.device_id for d in refs]

    def primary(self, role: DeviceRole) -> str | None:
        ids = self.device_ids(role)
        return ids[0] if ids else None


class EndpointService:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def list(self, room_id: str | None = None) -> builtins.list[EndpointView]:
        stmt = select(InteractionEndpoint).order_by(InteractionEndpoint.name)
        if room_id:
            stmt = stmt.where(InteractionEndpoint.room_id == room_id)
        async with self.db.session() as s:
            endpoints = (await s.scalars(stmt)).all()
            refs = (await s.scalars(select(EndpointDevice))).all()
        by_ep: dict[str, builtins.list[EndpointDeviceRef]] = {}
        for r in refs:
            by_ep.setdefault(r.endpoint_id, []).append(
                EndpointDeviceRef(device_id=r.device_id, role=DeviceRole(r.role), priority=r.priority)
            )
        return [self._view(e, by_ep.get(e.id, [])) for e in endpoints]

    async def get(self, endpoint_id: str) -> EndpointView:
        async with self.db.session() as s:
            ep = await s.get(InteractionEndpoint, endpoint_id)
            if ep is None:
                raise NotFound(f"endpoint {endpoint_id} not found")
            refs = (await s.scalars(select(EndpointDevice).where(
                EndpointDevice.endpoint_id == endpoint_id))).all()
        return self._view(ep, [EndpointDeviceRef(device_id=r.device_id, role=DeviceRole(r.role),
                                                 priority=r.priority) for r in refs])

    async def create(self, data: EndpointIn) -> EndpointView:
        await self._validate_devices(data.room_id, data.devices)
        async with self.db.session() as s:
            ep = InteractionEndpoint(name=data.name, room_id=data.room_id, enabled=data.enabled,
                                     priority=data.priority, arbitration_group=data.arbitration_group,
                                     language=data.language, config=data.config.model_dump(mode="json"))
            s.add(ep)
            await s.flush()
            for ref in data.devices:
                s.add(EndpointDevice(endpoint_id=ep.id, device_id=ref.device_id, role=ref.role,
                                     priority=ref.priority))
            endpoint_id = ep.id
        return await self.get(endpoint_id)

    async def update(self, endpoint_id: str, patch: EndpointPatch) -> EndpointView:
        current = await self.get(endpoint_id)
        room_id = patch.room_id or current.room_id
        if patch.devices is not None:
            await self._validate_devices(room_id, patch.devices)
        async with self.db.session() as s:
            ep = await s.get(InteractionEndpoint, endpoint_id)
            if ep is None:
                raise NotFound(f"endpoint {endpoint_id} not found")
            for field in ("name", "room_id", "enabled", "priority", "arbitration_group"):
                value = getattr(patch, field)
                if value is not None:
                    setattr(ep, field, value)
            if "language" in patch.model_fields_set:
                ep.language = patch.language
            if patch.config is not None:
                ep.config = patch.config.model_dump(mode="json")
            if patch.devices is not None:
                await s.execute(delete(EndpointDevice).where(EndpointDevice.endpoint_id == endpoint_id))
                for ref in patch.devices:
                    s.add(EndpointDevice(endpoint_id=endpoint_id, device_id=ref.device_id,
                                         role=ref.role, priority=ref.priority))
        return await self.get(endpoint_id)

    async def delete(self, endpoint_id: str) -> None:
        async with self.db.session() as s:
            ep = await s.get(InteractionEndpoint, endpoint_id)
            if ep is None:
                raise NotFound(f"endpoint {endpoint_id} not found")
            await s.delete(ep)

    async def _validate_devices(self, room_id: str, refs: builtins.list[EndpointDeviceRef]) -> None:
        if not refs:
            return
        async with self.db.session() as s:
            rows = (await s.scalars(select(Device).where(
                Device.id.in_([r.device_id for r in refs])))).all()
        found = {d.id: d for d in rows}
        for ref in refs:
            device = found.get(ref.device_id)
            if device is None:
                raise ValidationFailed(f"device {ref.device_id} does not exist")
            if device.room_id not in (None, room_id):
                raise ValidationFailed(
                    f"device {device.name} belongs to another room; an endpoint may only use "
                    "devices of its own room"
                )
        if sum(1 for r in refs if r.role == DeviceRole.SPEAKER) > 1:
            raise ValidationFailed("an endpoint has at most one speaker")

    @staticmethod
    def _view(ep: InteractionEndpoint, refs: builtins.list[EndpointDeviceRef]) -> EndpointView:
        return EndpointView(id=ep.id, name=ep.name, room_id=ep.room_id, enabled=ep.enabled,
                            priority=ep.priority, arbitration_group=ep.arbitration_group,
                            language=ep.language,
                            config=EndpointConfig.model_validate(ep.config or {}), devices=refs)
