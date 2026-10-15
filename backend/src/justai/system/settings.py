"""System-wide settings edited in the admin UI (stored under settings key ``system``)."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator


class Retention(BaseModel):
    events_days: int = Field(90, ge=1)
    transcripts_days: int = Field(365, ge=1)
    sightings_days: int = Field(60, ge=1)
    tool_executions_days: int = Field(90, ge=1)


class SystemSettings(BaseModel):
    timezone: str = "Europe/Rome"

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {v}") from exc
        return v

    discovery_cidrs: list[str] = Field(default_factory=list)
    retention: Retention = Field(default_factory=Retention)
    store_face_thumbnails: bool = True
