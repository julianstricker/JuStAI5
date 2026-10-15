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
    EventTypeSpec("audio.wakeword.detected", "Wakeword-Kandidat erkannt", payload_model=WakewordPayload),
    EventTypeSpec("audio.wakeword.accepted", "Wakeword nach Arbitrierung akzeptiert", durable=True),
    EventTypeSpec("audio.wakeword.rejected", "Wakeword-Kandidat verworfen (Arbitrierung/Echo)"),
    EventTypeSpec("audio.echo.suppressed", "Eigene Sprachausgabe als Eingabe erkannt und verworfen"),
    EventTypeSpec("conversation.session.started", "Gesprächssession gestartet", durable=True),
    EventTypeSpec("conversation.session.ended", "Gesprächssession beendet", durable=True),
    EventTypeSpec("conversation.state.changed", "Zustandswechsel einer Gesprächssession"),
    EventTypeSpec("conversation.user.utterance", "Benutzeräußerung", durable=False,
                  sensitivity=Sensitivity.PERSONAL),
    EventTypeSpec("conversation.assistant.utterance", "Antwort des Assistenten",
                  sensitivity=Sensitivity.PERSONAL),
    EventTypeSpec("conversation.barge_in", "Benutzer hat die Ausgabe unterbrochen"),
    # vision
    EventTypeSpec("vision.motion.started", "Bewegung erkannt"),
    EventTypeSpec("vision.motion.ended", "Bewegung beendet"),
    EventTypeSpec("vision.object.appeared", "Objekt erschienen", durable=True,
                  payload_model=ObjectPayload),
    EventTypeSpec("vision.object.left", "Objekt nicht mehr sichtbar", payload_model=ObjectPayload),
    EventTypeSpec("vision.person.recognized", "Bekannte Person wiedererkannt", durable=True,
                  priority=EventPriority.HIGH, sensitivity=Sensitivity.BIOMETRIC,
                  payload_model=PersonRecognizedPayload),
    EventTypeSpec("vision.face.unknown", "Unbekanntes Gesicht", sensitivity=Sensitivity.BIOMETRIC),
    EventTypeSpec("vision.watch.triggered", "Überwachungsaufgabe ausgelöst", durable=True,
                  priority=EventPriority.HIGH),
    EventTypeSpec("vision.state.changed", "Visueller Zustand geändert (z. B. Tor offen)",
                  durable=True),
    # devices
    EventTypeSpec("device.status.changed", "Gerätestatus geändert", durable=True),
    EventTypeSpec("device.discovered", "Neues Gerät gefunden"),
    EventTypeSpec("ptz.tracking.started", "Kamera-Tracking gestartet"),
    EventTypeSpec("ptz.tracking.stopped", "Kamera-Tracking beendet"),
    # displays
    EventTypeSpec("display.presentation.status", "Statuswechsel einer Darstellung"),
    EventTypeSpec("display.interaction", "Benutzerinteraktion auf einem Display", durable=True),
    EventTypeSpec("display.connected", "Display verbunden"),
    EventTypeSpec("display.disconnected", "Display getrennt"),
    # automation / system
    EventTypeSpec("automation.run.started", "Automation ausgeführt", durable=True),
    EventTypeSpec("automation.run.finished", "Automation beendet", durable=True),
    EventTypeSpec("schedule.tick", "Zeitplan-Auslöser"),
    EventTypeSpec("memory.created", "Erinnerung gespeichert", sensitivity=Sensitivity.PERSONAL),
    EventTypeSpec("identity.person.enrolled", "Person biometrisch registriert", durable=True,
                  sensitivity=Sensitivity.BIOMETRIC),
    EventTypeSpec("plugin.status.changed", "Pluginstatus geändert", durable=True),
    EventTypeSpec("tool.executed", "Tool ausgeführt"),
    EventTypeSpec("ai.provider.fallback", "KI-Provider-Fallback verwendet", durable=True,
                  priority=EventPriority.HIGH),
    EventTypeSpec("system.event_loop_detected", "Event-Schleife erkannt und gestoppt",
                  durable=True, priority=EventPriority.HIGH),
    EventTypeSpec("manual.test", "Manuell ausgelöstes Test-Event"),
]


def build_core_catalog() -> EventCatalog:
    catalog = EventCatalog()
    for spec in CORE_EVENT_TYPES:
        catalog.register(spec)
    return catalog
