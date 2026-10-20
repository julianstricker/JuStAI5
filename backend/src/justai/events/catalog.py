"""Catalog of known event types (typed, versioned, documented)."""

from __future__ import annotations

import builtins
from dataclasses import dataclass

from justai_sdk.events import Durability, EventPriority, Sensitivity
from pydantic import BaseModel, ValidationError

from justai.common.errors import ValidationFailed


@dataclass(frozen=True)
class EventTypeSpec:
    type: str
    description: str
    durable: bool = False
    priority: EventPriority = EventPriority.NORMAL
    sensitivity: Sensitivity = Sensitivity.NORMAL
    payload_model: builtins.type[BaseModel] | None = None
    version: int = 1
    owner: str = "core"  # core | plugin:<id>


class EventCatalog:
    def __init__(self) -> None:
        self._specs: dict[str, EventTypeSpec] = {}

    def register(self, spec: EventTypeSpec) -> None:
        existing = self._specs.get(spec.type)
        if existing and existing.owner != spec.owner:
            raise ValueError(f"event type {spec.type} already registered by {existing.owner}")
        self._specs[spec.type] = spec

    def unregister_owner(self, owner: str) -> None:
        for key in [k for k, s in self._specs.items() if s.owner == owner]:
            del self._specs[key]

    def get(self, type: str) -> EventTypeSpec | None:
        return self._specs.get(type)

    def all(self) -> list[EventTypeSpec]:
        return sorted(self._specs.values(), key=lambda s: s.type)

    def default_durability(self, type: str) -> Durability:
        spec = self._specs.get(type)
        return Durability.DURABLE if spec and spec.durable else Durability.EPHEMERAL

    def validate_payload(self, type: str, payload: dict[str, object]) -> None:
        spec = self._specs.get(type)
        if spec is None or spec.payload_model is None:
            return
        try:
            spec.payload_model.model_validate(payload)
        except ValidationError as exc:
            raise ValidationFailed(f"invalid payload for {type}", errors=exc.errors()) from exc


# ------------------------------------------------------------------ core types


class PersonRecognizedPayload(BaseModel):
    person_id: str
    person_name: str | None = None
    camera_id: str
    similarity: float
    match_level: str  # strong | weak
    track_id: str | None = None
    away_s: int | None = None  # seconds since last seen on any camera (absence before this sighting)


class ObjectPayload(BaseModel):
    label: str
    camera_id: str
    track_id: str
    score: float
    entity_id: str | None = None  # e.g. registered pet
    zone: str | None = None


class WakewordPayload(BaseModel):
    endpoint_id: str
    model: str
    score: float


CORE_EVENT_TYPES: list[EventTypeSpec] = [
    # audio / conversation
    EventTypeSpec("audio.wakeword.detected", "Wakeword candidate detected", payload_model=WakewordPayload),
    EventTypeSpec("audio.wakeword.accepted", "Wakeword accepted after arbitration", durable=True),
    EventTypeSpec("audio.wakeword.rejected", "Wakeword candidate rejected (arbitration/echo)"),
    EventTypeSpec("audio.echo.suppressed", "Own speech output recognised as input and dropped"),
    EventTypeSpec("conversation.session.started", "Conversation session started", durable=True),
    EventTypeSpec("conversation.session.ended", "Conversation session ended", durable=True),
    EventTypeSpec("conversation.state.changed", "State change of a conversation session"),
    EventTypeSpec("conversation.user.utterance", "User utterance", durable=False,
                  sensitivity=Sensitivity.PERSONAL),
    EventTypeSpec("conversation.assistant.utterance", "Assistant answer",
                  sensitivity=Sensitivity.PERSONAL),
    EventTypeSpec("conversation.barge_in", "User interrupted the output"),
    # vision
    EventTypeSpec("vision.motion.started", "Motion detected"),
    EventTypeSpec("vision.motion.ended", "Motion ended"),
    EventTypeSpec("vision.object.appeared", "Object appeared", durable=True,
                  payload_model=ObjectPayload),
    EventTypeSpec("vision.object.left", "Object no longer visible", payload_model=ObjectPayload),
    EventTypeSpec("vision.person.recognized", "Known person recognised", durable=True,
                  priority=EventPriority.HIGH, sensitivity=Sensitivity.BIOMETRIC,
                  payload_model=PersonRecognizedPayload),
    EventTypeSpec("vision.face.unknown", "Unknown face", sensitivity=Sensitivity.BIOMETRIC),
    EventTypeSpec("vision.watch.triggered", "Watch triggered", durable=True,
                  priority=EventPriority.HIGH),
    EventTypeSpec("vision.state.changed", "Visual state changed (e.g. gate open)",
                  durable=True),
    # devices
    EventTypeSpec("device.status.changed", "Device status changed", durable=True),
    EventTypeSpec("device.discovered", "New device found"),
    EventTypeSpec("ptz.tracking.started", "Camera tracking started"),
    EventTypeSpec("ptz.tracking.stopped", "Camera tracking stopped"),
    # displays
    EventTypeSpec("display.presentation.status", "Status change of a presentation"),
    EventTypeSpec("display.interaction", "User interaction on a display", durable=True),
    EventTypeSpec("display.connected", "Display connected"),
    EventTypeSpec("display.disconnected", "Display disconnected"),
    # automation / system
    EventTypeSpec("automation.run.started", "Automation run started", durable=True),
    EventTypeSpec("automation.run.finished", "Automation run finished", durable=True),
    EventTypeSpec("schedule.tick", "Schedule trigger"),
    EventTypeSpec("memory.created", "Memory stored", sensitivity=Sensitivity.PERSONAL),
    EventTypeSpec("identity.person.enrolled", "Person biometrically enrolled", durable=True,
                  sensitivity=Sensitivity.BIOMETRIC),
    EventTypeSpec("plugin.status.changed", "Plugin status changed", durable=True),
    EventTypeSpec("tool.executed", "Tool executed"),
    EventTypeSpec("ai.provider.fallback", "AI provider fallback used", durable=True,
                  priority=EventPriority.HIGH),
    EventTypeSpec("system.event_loop_detected", "Event loop detected and stopped",
                  durable=True, priority=EventPriority.HIGH),
    EventTypeSpec("manual.test", "Manually triggered test event"),
]


def build_core_catalog() -> EventCatalog:
    catalog = EventCatalog()
    for spec in CORE_EVENT_TYPES:
        catalog.register(spec)
    return catalog
