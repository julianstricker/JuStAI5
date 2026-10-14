"""Vision ports: object detection and face analysis.

Images are BGR ``uint8`` arrays (OpenCV convention). Methods are synchronous and
CPU/GPU bound; the core runs them in a worker pool and shares one model instance
between all cameras.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, ConfigDict, Field

Image = npt.NDArray[np.uint8]


class BBox(BaseModel):
    """Normalised bounding box (0..1 relative to image width/height)."""

    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    def iou(self, other: BBox) -> float:
        x1, y1 = max(self.x, other.x), max(self.y, other.y)
        x2 = min(self.x + self.w, other.x + other.w)
        y2 = min(self.y + self.h, other.y + other.h)
        inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0


class Detection(BaseModel):
    label: str
    score: float
    bbox: BBox


class FaceObservation(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    bbox: BBox
    score: float
    landmarks: list[tuple[float, float]] = Field(default_factory=list)  # normalised
    raw: list[float] = Field(default_factory=list)  # detector-native row, for alignment
    sharpness: float = 0.0
    brightness: float = 0.0
    size_px: int = 0
    frontalness: float = 0.0  # 1 = frontal, 0 = profile


@runtime_checkable
class ObjectDetector(Protocol):
    detector_id: str
    labels: list[str]

    def detect(self, image: Image, min_score: float = 0.4) -> list[Detection]: ...


@runtime_checkable
class FaceAnalyzer(Protocol):
    analyzer_id: str
    embedding_model: str
    embedding_dim: int
    match_threshold: float  # cosine similarity above which a match is plausible
    strong_match_threshold: float

    def detect_faces(self, image: Image) -> list[FaceObservation]: ...

    def embed(self, image: Image, face: FaceObservation) -> npt.NDArray[np.float32]: ...
