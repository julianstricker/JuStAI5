"""Event model shared between the core and plugins.

Every event is versioned (``type`` + ``version``) and carries correlation data
(``correlation_id``, ``causation_id``, ``hop``) so that the automation engine can
detect and stop event loops.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime
from enum import IntEnum, StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7 (millisecond timestamp + randomness); stdlib only has it from 3.14."""
    ts_ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ts_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version
    value |= ((rand >> 62) & 0xFFF) << 64  # rand_a (12 bits)
    value |= 0b10 << 62  # variant
    value |= rand & ((1 << 62) - 1)  # rand_b
    return uuid.UUID(int=value)


def new_id(prefix: str = "") -> str:
    """Time-ordered unique id (UUIDv7) with an optional readable prefix."""
    value = str(uuid7())
    return f"{prefix}-{value}" if prefix else value


def utcnow() -> datetime:
    return datetime.now(UTC)


class EventPriority(IntEnum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


class Durability(StrEnum):
    EPHEMERAL = "ephemeral"  # delivered in-memory only (e.g. audio levels, per-frame data)
    DURABLE = "durable"  # persisted and replayable (e.g. person recognized, automation fired)


class Sensitivity(StrEnum):
    NORMAL = "normal"
    PERSONAL = "personal"
    BIOMETRIC = "biometric"


class EventSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = "system"  # system | device | plugin | automation | session | user | tool | display
    id: str | None = None
    device_id: str | None = None
    room_id: str | None = None
    endpoint_id: str | None = None
    plugin_id: str | None = None
    session_id: str | None = None
    user_id: str | None = None


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: new_id("evt"))
    type: str
    version: int = 1
    timestamp: datetime = Field(default_factory=utcnow)
    source: EventSource = Field(default_factory=EventSource)
    payload: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str | None = None
    causation_id: str | None = None
    hop: int = 0
    priority: EventPriority = EventPriority.NORMAL
    durability: Durability | None = None  # None -> use the catalog default for the type
    dedup_key: str | None = None
    sensitivity: Sensitivity = Sensitivity.NORMAL

    def caused(self, type: str, payload: dict[str, Any] | None = None, **kw: Any) -> Event:
        """Create a follow-up event that inherits correlation data from this one."""
        return Event(
            type=type,
            payload=payload or {},
            correlation_id=self.correlation_id or self.id,
            causation_id=self.id,
            hop=self.hop + 1,
            **kw,
        )
