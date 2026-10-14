"""Wakeword port. Detection always runs locally on 16 kHz mono PCM."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from justai_sdk.audio import Int16Array


class WakewordModelInfo(BaseModel):
    id: str
    name: str
    phrase: str
    languages: list[str] = []


class WakeDetection(BaseModel):
    model: str
    score: float


@runtime_checkable
class WakewordDetector(Protocol):
    frame_samples: int  # preferred number of 16 kHz samples per call

    def process(self, pcm16k: Int16Array) -> list[WakeDetection]:
        """Return the per-model scores for this frame (only scores >= 0.01 are reported)."""
        ...

    def reset(self) -> None: ...


@runtime_checkable
class WakewordProvider(Protocol):
    provider_id: str

    def list_models(self) -> list[WakewordModelInfo]: ...

    def create_detector(self, models: list[str]) -> WakewordDetector: ...
