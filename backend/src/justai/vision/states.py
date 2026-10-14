"""Learnable visual state detectors (e.g. "garage door open/closed").

A detector watches a region of a fixed camera. The user teaches it by labelling the
current image ("the door is open now"); several references per state can be added
(day/night). Classification is nearest-reference on normalised, downscaled
grayscale crops, so no model training or new code is required.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from justai_sdk.events import Event, EventSource
from sqlalchemy import select

from justai.common.errors import NotFound, Unavailable, ValidationFailed
from justai.db.engine import Database
from justai.db.models import VisionWatch
from justai.events.bus import EventBus
from justai.logging import get_logger

if TYPE_CHECKING:
    from justai.vision.engine import VisionEngine

log = get_logger(__name__)
SIZE = 48


def features(image: np.ndarray, zone: dict[str, float] | None) -> list[float]:
    h, w = image.shape[:2]
    if zone:
        x0, y0 = int(zone["x"] * w), int(zone["y"] * h)
        x1, y1 = int((zone["x"] + zone["w"]) * w), int((zone["y"] + zone["h"]) * h)
        image = image[max(0, y0):max(y0 + 1, y1), max(0, x0):max(x0 + 1, x1)]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (SIZE, SIZE), interpolation=cv2.INTER_AREA).astype(np.float32)
    small = cv2.equalizeHist(small.astype(np.uint8)).astype(np.float32)
    v = small.reshape(-1) - small.mean()
    return (v / (np.linalg.norm(v) + 1e-6)).tolist()


def classify(feat: list[float], references: dict[str, list[list[float]]]) -> tuple[str | None, float, float]:
    """Returns (state, best similarity, margin to the second best state)."""
    x = np.asarray(feat, dtype=np.float32)
    scores = {state: max(float(np.dot(x, np.asarray(r, dtype=np.float32))) for r in refs)
              for state, refs in references.items() if refs}
    if not scores:
        return None, 0.0, 0.0
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    best_state, best = ranked[0]
    margin = best - (ranked[1][1] if len(ranked) > 1 else 0.0)
    return best_state, best, margin


class StateDetectors:
    def __init__(self, db: Database, bus: EventBus, engine: VisionEngine) -> None:
        self.db = db
        self.bus = bus
        self.engine = engine
        self._task: asyncio.Task[None] | None = None
        self._pending: dict[str, tuple[str, int]] = {}

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="vision-states")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _detectors(self) -> list[VisionWatch]:
        async with self.db.session() as s:
            rows = (await s.scalars(select(VisionWatch).where(VisionWatch.enabled))).all()
        return [r for r in rows if (r.spec or {}).get("kind") == "state"]

    async def find(self, name: str) -> VisionWatch | None:
        for d in await self._detectors():
            if d.name.lower() == name.strip().lower():
                return d
        return None

    async def _image(self, device_id: str) -> np.ndarray:
        frame = self.engine.latest_frame(device_id)
        if frame is not None:
            return frame
        jpeg = await self.engine.devices.snapshot(device_id, width=640)
        image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise Unavailable("camera image unavailable")
        return image

    async def teach(self, name: str, state: str, device_id: str, zone: dict[str, float] | None,
                    created_by: str) -> dict[str, Any]:
        image = await self._image(device_id)
        detector = await self.find(name)
        async with self.db.session() as s:
            if detector is None:
                detector = VisionWatch(name=name, camera_device_id=device_id, created_by=created_by,
                                       spec={"kind": "state", "zone": zone, "references": {},
                                             "interval_s": 30})
                s.add(detector)
                await s.flush()
            else:
                detector = await s.get(VisionWatch, detector.id)
                assert detector is not None
                if detector.camera_device_id != device_id:
                    raise ValidationFailed("this detector belongs to another camera")
            spec = dict(detector.spec)
            refs = {k: list(v) for k, v in (spec.get("references") or {}).items()}
            refs.setdefault(state, []).append(features(image, spec.get("zone")))
            refs[state] = refs[state][-8:]
            spec["references"] = refs
            detector.spec = spec
            detector.state = {**(detector.state or {}), "current": state, "since": time.time()}
            counts = {k: len(v) for k, v in refs.items()}
        return {"detector": name, "states": counts,
                "ready": len(counts) >= 2, "hint": None if len(counts) >= 2 else
                "Zeige mir noch mindestens einen weiteren Zustand, damit ich unterscheiden kann."}

    async def current(self, name: str) -> dict[str, Any]:
        detector = await self.find(name)
        if detector is None:
            raise NotFound(f"no state detector '{name}'")
        image = await self._image(detector.camera_device_id)
        spec = detector.spec or {}
        state, sim, margin = classify(features(image, spec.get("zone")), spec.get("references") or {})
        return {"detector": name, "state": state, "similarity": round(sim, 3),
                "margin": round(margin, 3), "reliable": margin >= 0.05}

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(10)
            try:
                for detector in await self._detectors():
                    await self._check(detector)
            except Exception as exc:
                log.warning("state detector loop failed", error=str(exc))

    async def _check(self, detector: VisionWatch) -> None:
        spec = detector.spec or {}
        refs = spec.get("references") or {}
        if len(refs) < 2:
            return
        last = float((detector.state or {}).get("checked_at", 0))
        if time.time() - last < float(spec.get("interval_s", 30)):
            return
        try:
            image = await self._image(detector.camera_device_id)
        except Exception:
            return
        state, sim, margin = classify(features(image, spec.get("zone")), refs)
        current = (detector.state or {}).get("current")
        async with self.db.session() as s:
            row = await s.get(VisionWatch, detector.id)
            if row is None:
                return
            row.state = {**(row.state or {}), "checked_at": time.time(), "last_similarity": sim}
            if state is None or state == current or margin < 0.05:
                self._pending.pop(detector.id, None)
                return
            pending_state, count = self._pending.get(detector.id, (state, 0))
            count = count + 1 if pending_state == state else 1
            self._pending[detector.id] = (state, count)
            if count < 2:  # require two consecutive observations
                return
            row.state = {**row.state, "current": state, "since": time.time()}
            self._pending.pop(detector.id, None)
        runtime = self.engine.devices.get(detector.camera_device_id)
        await self.bus.publish(Event(type="vision.state.changed", payload={
            "detector_id": detector.id, "name": detector.name, "state": state, "previous": current,
            "camera_id": detector.camera_device_id, "similarity": round(sim, 3)},
            source=EventSource(kind="device", device_id=detector.camera_device_id,
                               room_id=runtime.room_id if runtime else None)))
