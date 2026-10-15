"""Vision engine: staged, resource-friendly analysis of camera streams.

    frames (substream, low fps) -> privacy mask -> motion -> object detection
    (only on motion / active tracks) -> tracking -> face check on a full-resolution
    snapshot (only for unidentified person tracks) -> events, sightings, watches

One detector and one face model instance are shared by all cameras. Inference
runs on a bounded worker pool; conversations and PTZ tracking get priority by
lowering the background frame rate while they are active.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import cv2
import numpy as np
from justai_sdk.events import Event, EventSource
from justai_sdk.ports.devices import Capability
from justai_sdk.ports.vision import BBox, Detection, FaceAnalyzer, Image, ObjectDetector
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from justai.common.supervisor import Supervisor
from justai.db.engine import Database
from justai.db.models import Sighting, VisionWatch
from justai.devices.manager import DeviceManager, DeviceRuntime
from justai.devices.service import DevicePatch, DeviceService
from justai.events.bus import EventBus
from justai.identity.service import IdentityService, quality_issues
from justai.logging import get_logger
from justai.media.go2rtc import Go2rtcClient
from justai.plugins.providers import ProviderRegistry
from justai.rooms.service import RoomService
from justai.system.telemetry import TelemetryHub
from justai.vision.frames import DeviceFrameSource, FfmpegFrameSource, MotionDetector, apply_privacy_mask
from justai.vision.tracker import IouTracker, Track

log = get_logger(__name__)

NEVER_SEEN_AWAY_S = 365 * 24 * 3600
DEFAULT_LABELS = ["person", "dog", "cat", "car", "truck", "bicycle", "motorcycle", "bird"]


class PrivacyZone(BaseModel):
    name: str = "Zone"
    points: list[tuple[float, float]]


class CameraVisionConfig(BaseModel):
    enabled: bool = True
    fps: float = Field(2.0, ge=0.2, le=10)
    motion: bool = True
    objects: bool = True
    labels: list[str] = Field(default_factory=lambda: list(DEFAULT_LABELS))
    faces: bool = True
    min_score: float = Field(0.5, ge=0.1, le=0.95)
    privacy_zones: list[PrivacyZone] = Field(default_factory=list)
    heartbeat_s: float = 20.0  # run the detector this often even without motion


@dataclass
class CameraStats:
    frames: int = 0
    analyzed: int = 0
    motion: bool = False
    tracks: int = 0
    fps: float = 0.0
    detect_ms: float = 0.0
    face_checks: int = 0


@dataclass
class CameraState:
    device_id: str
    name: str
    room_id: str | None
    config: CameraVisionConfig
    tracker: IouTracker = field(default_factory=IouTracker)
    motion: MotionDetector = field(default_factory=MotionDetector)
    stats: CameraStats = field(default_factory=CameraStats)
    latest: tuple[float, Image] | None = None
    last_detect: float = 0.0
    boost_until: float = 0.0  # run detection on every frame (PTZ tracking)
    unknown_face_at: float = 0.0
    recognized_at: dict[str, float] = field(default_factory=dict)


TrackListener = Callable[[str, float, list[Track], tuple[int, int]], None]


class VisionEngine:
    def __init__(self, *, db: Database, bus: EventBus, devices: DeviceManager,
                 device_records: DeviceService, rooms: RoomService, providers: ProviderRegistry,
                 go2rtc: Go2rtcClient, identity: IdentityService, telemetry: TelemetryHub,
                 supervisor: Supervisor, workers: int = 2) -> None:
        self.db = db
        self.bus = bus
        self.devices = devices
        self.device_records = device_records
        self.rooms = rooms
        self.providers = providers
        self.go2rtc = go2rtc
        self.identity = identity
        self.telemetry = telemetry
        self.supervisor = supervisor
        self.cameras: dict[str, CameraState] = {}
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vision")
        self._sem = asyncio.Semaphore(workers)
        self._track_listeners: dict[str, list[TrackListener]] = {}
        self._watches: dict[str, list[VisionWatch]] = {}
        self.background_slowdown = 1.0  # >1 while conversations are active
        # person_id -> wall-clock time the person was last seen on any camera. Used to tell
        # "came back after an absence" apart from re-identifying someone who never left
        # (tracks break up when a person sits still between detector runs).
        self._person_seen: dict[str, float] = {}
        devices.on_ready_change(self._on_device)

    # --------------------------------------------------------------- providers
    @property
    def detector(self) -> ObjectDetector | None:
        entries = self.providers.all("object_detector")
        return entries[0] if entries else None

    @property
    def faces(self) -> FaceAnalyzer | None:
        entries = self.providers.all("face_analyzer")
        return entries[0] if entries else None

    def labels(self) -> list[str]:
        det = self.detector
        return list(det.labels) if det else []

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.identity.reload_gallery()
        await self.reload_watches()
        for rt in self.devices.runtimes():
            if rt.online:
                await self._on_device(rt, True)

    async def stop(self) -> None:
        for device_id in list(self.cameras):
            await self.supervisor.stop(f"vision:{device_id}")
        self._pool.shutdown(wait=False, cancel_futures=True)

    async def _on_device(self, runtime: DeviceRuntime, ready: bool) -> None:
        if not ready:
            await self.supervisor.stop(f"vision:{runtime.device_id}")
            self.cameras.pop(runtime.device_id, None)
            self.telemetry.forget(f"vision.camera.{runtime.device_id}")
            return
        if Capability.VIDEO_INPUT not in runtime.capabilities:
            return
        await self.reconfigure(runtime.device_id)

    async def reconfigure(self, device_id: str) -> None:
        runtime = self.devices.get(device_id)
        await self.supervisor.stop(f"vision:{device_id}")
        self.cameras.pop(device_id, None)
        if runtime is None or not runtime.online:
            return
        cfg = CameraVisionConfig.model_validate((runtime.settings or {}).get("vision") or {})
        if runtime.room_id:
            room = await self.rooms.get(runtime.room_id)
            policy = RoomService.policy(room)
            if not policy.vision_allowed:
                cfg.enabled = False
            if not policy.face_recognition_allowed:
                cfg.faces = False
        state = CameraState(device_id, runtime.name, runtime.room_id, cfg)
        self.cameras[device_id] = state
        if cfg.enabled:
            self.supervisor.start(f"vision:{device_id}", lambda: self._run(state), max_backoff_s=60)

    async def set_config(self, device_id: str, cfg: CameraVisionConfig) -> None:
        await self.device_records.update(device_id, DevicePatch(settings={"vision": cfg.model_dump()}), [])
        runtime = self.devices.get(device_id)
        if runtime is not None:
            runtime.settings = {**runtime.settings, "vision": cfg.model_dump()}
        await self.reconfigure(device_id)

    def config(self, device_id: str) -> CameraVisionConfig:
        state = self.cameras.get(device_id)
        if state is not None:
            return state.config
        runtime = self.devices.get(device_id)
        return CameraVisionConfig.model_validate(((runtime.settings if runtime else {}) or {}).get("vision") or {})

    def active_cameras(self) -> list[str]:
        return [d for d, s in self.cameras.items() if s.config.enabled and self.supervisor.has(f"vision:{d}")]

    # -------------------------------------------------------------- subscribers
    def subscribe_tracks(self, device_id: str, listener: TrackListener) -> Callable[[], None]:
        self._track_listeners.setdefault(device_id, []).append(listener)
        state = self.cameras.get(device_id)
        if state:
            state.boost_until = float("inf")

        def unsubscribe() -> None:
            listeners = self._track_listeners.get(device_id, [])
            if listener in listeners:
                listeners.remove(listener)
            if not listeners and device_id in self.cameras:
                self.cameras[device_id].boost_until = 0.0

        return unsubscribe

    async def reload_watches(self) -> None:
        async with self.db.session() as s:
            rows = (await s.scalars(select(VisionWatch).where(VisionWatch.enabled))).all()
        now = datetime.now(UTC)
        self._watches = {}
        for w in rows:
            if w.expires_at and w.expires_at < now:
                continue
            self._watches.setdefault(w.camera_device_id, []).append(w)

    # -------------------------------------------------------------- the pipeline
    async def _run(self, state: CameraState) -> None:
        runtime = self.devices.require(state.device_id)
        assert runtime.handle is not None
        custom = runtime.handle.video_source()
        fps = state.config.fps
        if custom is not None:
            source: Any = DeviceFrameSource(custom, fps)
        else:
            stream = runtime.sub_stream or runtime.stream
            if not stream:
                raise RuntimeError("camera has no stream")
            source = FfmpegFrameSource(self.go2rtc.rtsp(stream, video_only=True), fps)
        zones = [z.points for z in state.config.privacy_zones]
        window_t = time.monotonic()
        window_frames = 0
        try:
            async for t, frame in source.frames():
                state.stats.frames += 1
                window_frames += 1
                if t - window_t >= 5:
                    state.stats.fps = window_frames / (t - window_t)
                    window_t, window_frames = t, 0
                frame = apply_privacy_mask(frame, zones)
                state.latest = (t, frame)
                await self._process(state, t, frame)
                self.telemetry.publish(f"vision.camera.{state.device_id}", vars(state.stats))
        finally:
            for tr in state.tracker.clear():
                await self._track_left(state, tr)

    async def _process(self, state: CameraState, t: float, frame: Image) -> None:
        cfg = state.config
        if cfg.motion:
            change = state.motion.update(frame, t)
            state.stats.motion = state.motion.active
            if change is not None:
                await self._emit(state, "vision.motion.started" if change else "vision.motion.ended",
                                 {"camera_id": state.device_id, "score": round(state.motion.score, 4)})
        detector = self.detector
        if not cfg.objects or detector is None:
            return
        boosted = t < state.boost_until
        tracks_active = bool(state.tracker.tracks)
        interval = (1.0 / cfg.fps) * (1.0 if boosted else self.background_slowdown)
        due = t - state.last_detect >= interval
        heartbeat = t - state.last_detect >= cfg.heartbeat_s
        if not boosted and not heartbeat and (not due or not (state.motion.active or tracks_active or not cfg.motion)):
            return
        state.last_detect = t
        started = time.perf_counter()
        async with self._sem:
            dets: list[Detection] = await asyncio.get_running_loop().run_in_executor(
                self._pool, detector.detect, frame, cfg.min_score)
        state.stats.detect_ms = 0.8 * state.stats.detect_ms + 0.2 * (time.perf_counter() - started) * 1000
        state.stats.analyzed += 1
        relevant = [d for d in dets if d.label in cfg.labels]
        appeared, left = state.tracker.update(relevant, t)
        state.stats.tracks = len(state.tracker.confirmed())
        for tr in appeared:
            await self._track_appeared(state, tr)
        for tr in left:
            await self._track_left(state, tr)
        await self._check_watches(state, t)
        if cfg.faces:
            await self._check_faces(state, t)
        now_wall = time.time()
        for tr in state.tracker.confirmed():
            if tr.person_id:
                self._person_seen[tr.person_id] = now_wall
        for tr in state.tracker.confirmed():
            if t - tr.last_persisted > 60:
                await self._persist(state, tr)
        listeners = self._track_listeners.get(state.device_id)
        if listeners:
            size = (frame.shape[1], frame.shape[0])
            for listener in list(listeners):
                with contextlib.suppress(Exception):
                    listener(state.device_id, t, state.tracker.confirmed(), size)

    # ------------------------------------------------------------------ tracks
    async def _track_appeared(self, state: CameraState, tr: Track) -> None:
        if tr.label in ("dog", "cat"):
            pets = (await self.identity.pets_by_species()).get(tr.label, [])
            if len(pets) == 1:  # the only registered pet of that species
                tr.entity_id, tr.person_name = pets[0].id, pets[0].name
        await self._emit(state, "vision.object.appeared", {
            "label": tr.label, "camera_id": state.device_id, "track_id": tr.id,
            "score": round(tr.best_score, 3), "entity_id": tr.entity_id})
        await self._persist(state, tr)

    async def _track_left(self, state: CameraState, tr: Track) -> None:
        await self._persist(state, tr)
        await self._emit(state, "vision.object.left", {
            "label": tr.label, "camera_id": state.device_id, "track_id": tr.id,
            "score": round(tr.best_score, 3), "entity_id": tr.entity_id})

    async def _persist(self, state: CameraState, tr: Track) -> None:
        tr.last_persisted = tr.last_seen
        now = datetime.now(UTC)
        sid = tr.sighting_id or f"sight-{tr.id}-{int(time.time())}"
        tr.sighting_id = sid
        first_seen = datetime.fromtimestamp(time.time() - tr.age_s, UTC)
        values = {"id": sid, "camera_device_id": state.device_id, "room_id": state.room_id,
                  "label": tr.label, "person_id": tr.person_id or tr.entity_id, "track_id": tr.id,
                  "first_seen": first_seen, "last_seen": now, "best_score": tr.best_score,
                  "identity_similarity": tr.identity_similarity,
                  "meta": {"person_name": tr.person_name}}
        async with self.db.session() as s:
            stmt = insert(Sighting).values(**values)
            await s.execute(stmt.on_conflict_do_update(index_elements=[Sighting.id], set_={
                "last_seen": now, "best_score": tr.best_score, "person_id": values["person_id"],
                "identity_similarity": tr.identity_similarity, "meta": values["meta"]}))

    async def _check_watches(self, state: CameraState, t: float) -> None:
        for watch in self._watches.get(state.device_id, []):
            spec = watch.spec or {}
            if spec.get("kind", "objects") != "objects":
                continue
            labels = set(spec.get("labels") or [])
            min_score = float(spec.get("min_score", 0.5))
            zone = spec.get("zone")
            for tr in state.tracker.confirmed():
                if tr.label not in labels or tr.best_score < min_score or watch.id in tr.watches_fired:
                    continue
                if zone and not _point_in_polygon((tr.bbox.cx, tr.bbox.y + tr.bbox.h), zone["points"]):
                    continue
                tr.watches_fired.add(watch.id)
                cooldown = float(spec.get("cooldown_s", 120))
                last = float((watch.state or {}).get("last_fired", 0))
                if time.time() - last < cooldown:
                    continue
                watch.state = {**(watch.state or {}), "last_fired": time.time()}
                await self._emit(state, "vision.watch.triggered", {
                    "watch_id": watch.id, "name": watch.name, "label": tr.label,
                    "camera_id": state.device_id, "track_id": tr.id, "score": round(tr.best_score, 3)})

    # ------------------------------------------------------------------- faces
    async def _check_faces(self, state: CameraState, t: float) -> None:
        analyzer = self.faces
        if analyzer is None:
            return
        candidates = [tr for tr in state.tracker.confirmed()
                      if tr.label == "person" and tr.person_id is None and tr.face_checks < 6
                      and t - tr.last_face_check > 2.0]
        if not candidates:
            return
        try:
            jpeg = await self.devices.snapshot(state.device_id, width=1920)
        except Exception as exc:
            log.info("face snapshot failed", camera=state.device_id, error=str(exc))
            return
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            return
        image = cast(Image, decoded)
        image = apply_privacy_mask(image, [z.points for z in state.config.privacy_zones])
        state.stats.face_checks += 1
        async with self._sem:
            faces = await asyncio.get_running_loop().run_in_executor(self._pool, analyzer.detect_faces, image)
        for tr in candidates:
            tr.face_checks += 1
            tr.last_face_check = t
        for face in faces:
            track = next((tr for tr in candidates if _inside(face.bbox, tr.bbox)), None)
            if track is None or face.size_px < 40:  # too small for a reliable embedding
                continue
            async with self._sem:
                emb = await asyncio.get_running_loop().run_in_executor(self._pool, analyzer.embed, image, face)
            match = self.identity.match(emb, analyzer)
            if match is None:
                if t - state.unknown_face_at > 60:
                    state.unknown_face_at = t
                    await self._emit(state, "vision.face.unknown",
                                     {"camera_id": state.device_id, "track_id": track.id})
                continue
            track.identity_votes[match.person_id] = track.identity_votes.get(match.person_id, 0) + 1
            if match.level == "strong" or track.identity_votes[match.person_id] >= 2:
                track.person_id, track.person_name = match.person_id, match.name
                track.identity_similarity = round(match.similarity, 3)
                last = state.recognized_at.get(match.person_id, 0.0)
                state.recognized_at[match.person_id] = t
                await self._persist(state, track)
                if t - last > 120:  # do not re-announce the same person on short track loss
                    away_s = await self._away_seconds(match.person_id, track.id)
                    await self._emit(state, "vision.person.recognized", {
                        "person_id": match.person_id, "person_name": match.name,
                        "camera_id": state.device_id, "similarity": round(match.similarity, 3),
                        "match_level": match.level, "track_id": track.id, "away_s": away_s})
                self._person_seen[match.person_id] = time.time()

    async def _away_seconds(self, person_id: str, current_track: str) -> int:
        """Seconds since the person was last seen on any camera (before the current track).

        Falls back to persisted sightings after a restart; a person never seen before
        counts as away for a year.
        """
        seen = self._person_seen.get(person_id)
        if seen is None:
            async with self.db.session() as s:
                last = await s.scalar(select(func.max(Sighting.last_seen)).where(
                    Sighting.person_id == person_id, Sighting.track_id != current_track))
            seen = last.timestamp() if last is not None else None
        return int(time.time() - seen) if seen is not None else NEVER_SEEN_AWAY_S

    # ----------------------------------------------------------- on-demand use
    async def analyze_device(self, device_id: str) -> dict[str, Any]:
        """Full-resolution analysis of a fresh snapshot (tools, admin UI)."""
        jpeg = await self.devices.snapshot(device_id, width=1920)
        decoded = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None:
            raise RuntimeError("snapshot could not be decoded")
        image = cast(Image, decoded)
        cfg = self.config(device_id)
        image = apply_privacy_mask(image, [z.points for z in cfg.privacy_zones])
        result: dict[str, Any] = {"detections": [], "faces": [], "image_bgr": image}
        loop = asyncio.get_running_loop()
        if self.detector is not None:
            async with self._sem:
                dets = await loop.run_in_executor(self._pool, self.detector.detect, image, 0.4)
            result["detections"] = dets
        analyzer = self.faces
        if analyzer is not None and cfg.faces:
            async with self._sem:
                faces = await loop.run_in_executor(self._pool, analyzer.detect_faces, image)
            for face in faces:
                entry: dict[str, Any] = {"face": face, "match": None, "quality_issues": quality_issues(face)}
                if face.size_px >= 40:
                    async with self._sem:
                        emb = await loop.run_in_executor(self._pool, analyzer.embed, image, face)
                    entry["match"] = self.identity.match(emb, analyzer)
                result["faces"].append(entry)
        return result

    def latest_frame(self, device_id: str) -> Image | None:
        state = self.cameras.get(device_id)
        return state.latest[1] if state and state.latest else None

    async def _emit(self, state: CameraState, type: str, payload: dict[str, Any]) -> None:
        await self.bus.publish(Event(type=type, payload=payload, source=EventSource(
            kind="device", device_id=state.device_id, room_id=state.room_id)))


def _inside(face: BBox, body: BBox) -> bool:
    return body.x <= face.cx <= body.x + body.w and body.y <= face.cy <= body.y + body.h * 0.6


def _point_in_polygon(point: tuple[float, float], polygon: list[list[float]]) -> bool:
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1:
            inside = not inside
    return inside
