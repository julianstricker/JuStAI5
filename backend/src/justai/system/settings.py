"""System-wide settings edited in the admin UI (stored under settings key ``system``)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Retention(BaseModel):
    events_days: int = Field(90, ge=1)
    transcripts_days: int = Field(365, ge=1)
    sightings_days: int = Field(60, ge=1)
    snapshots_days: int = Field(14, ge=1)
    tool_executions_days: int = Field(90, ge=1)


class SystemSettings(BaseModel):
    timezone: str = "Europe/Rome"
    discovery_cidrs: list[str] = Field(default_factory=list)
    retention: Retention = Field(default_factory=Retention)
    store_face_thumbnails: bool = True
    vision_snapshots: bool = False
