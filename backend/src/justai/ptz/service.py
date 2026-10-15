"""PTZ service: manual control (priority), limits, tracking sessions, area search."""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from justai_sdk.events import Event, EventSource
from justai_sdk.ports.ptz import PtzController, PtzPreset

from justai.common.errors import NotFound, Unavailable
from justai.logging import get_logger
from justai.ptz.tracking import Command, TrackingParams, TrackingState, TrackingTarget, step
from justai.vision.tracker import Track

if TYPE_CHECKING:
    from justai.container import Container

log = get_logger(__name__)
MANUAL_OVERRIDE_S = 20.0


@dataclass
class TrackingSession:
    device_id: str
    state: TrackingState
    unsubscribe: Any
    queue: asyncio.Queue[tuple[float, list[Track]]]
    task: asyncio.Task[None] | None = None


class PtzService:
    def __init__(self, c: Container) -> None:
        self.c = c
        self.tracking: dict[str, TrackingSession] = {}
        self._manual_until: dict[str, float] = {}
        # Estimated pan/tilt offset since the last home move (for relative-only cameras).
        self._offset: dict[str, list[float]] = {}

    def controller(self, device_id: str) -> PtzController:
        rt = self.c.devices.require(device_id)
        assert rt.handle is not None
        ptz = rt.handle.ptz()
        if ptz is None:
            raise Unavailable(f"{rt.name} has no PTZ")
        return ptz

    def _limits(self, device_id: str) -> dict[str, float]:
        rt = self.c.devices.get(device_id)
        raw: Any = ((rt.settings if rt else {}) or {}).get("ptz_limits") or {}
        return {str(k): float(v) for k, v in dict(raw).items()}

    def _clamp(self, device_id: str, pan: float, tilt: float) -> tuple[float, float]:
        """Apply configured soft limits (in FOV units relative to home)."""
        limits = self._limits(device_id)
        off = self._offset.setdefault(device_id, [0.0, 0.0])
        lo_p, hi_p = limits.get("pan_min", -10.0), limits.get("pan_max", 10.0)
        lo_t, hi_t = limits.get("tilt_min", -10.0), limits.get("tilt_max", 10.0)
        pan = max(lo_p - off[0], min(hi_p - off[0], pan))
        tilt = max(lo_t - off[1], min(hi_t - off[1], tilt))
        return pan, tilt

    async def move(self, device_id: str, pan: float, tilt: float, zoom: float = 0.0, *,
                   manual: bool = True) -> None:
        if manual:
            # Manual control always wins over automatic tracking.
            self._manual_until[device_id] = time.monotonic() + MANUAL_OVERRIDE_S
            session = self.tracking.get(device_id)
            if session:
                session.state.paused_until = self._manual_until[device_id]
        pan, tilt = self._clamp(device_id, pan, tilt)
        if pan == 0 and tilt == 0 and zoom == 0:
            return
        await self.controller(device_id).move_relative(pan, tilt, zoom)
        off = self._offset.setdefault(device_id, [0.0, 0.0])
        off[0] += pan
        off[1] += tilt

    async def stop(self, device_id: str) -> None:
        await self.controller(device_id).stop()

    async def home(self, device_id: str) -> None:
        await self.controller(device_id).go_home()
        self._offset[device_id] = [0.0, 0.0]

    async def presets(self, device_id: str) -> list[PtzPreset]:
        ptz = self.controller(device_id)
        if not ptz.ptz_capabilities.presets:
            return []
        return await ptz.list_presets()

    async def goto_preset(self, device_id: str, preset_id: str, *, manual: bool = True) -> None:
        if manual:
            self._manual_until[device_id] = time.monotonic() + MANUAL_OVERRIDE_S
        await self.controller(device_id).goto_preset(preset_id)

    async def save_preset(self, device_id: str, name: str) -> PtzPreset:
        return await self.controller(device_id).save_preset(name)

    def status(self, device_id: str) -> dict[str, Any]:
        ptz = self.controller(device_id)
        session = self.tracking.get(device_id)
        manual = self._manual_until.get(device_id, 0.0)
        return {
            "capabilities": ptz.ptz_capabilities.model_dump(),
            "tracking": {"active": True, "target": session.state.target.value or session.state.target.kind,
                         "state": session.state.state} if session else None,
            "manual_override_until": manual if manual > time.monotonic() else None,
            "offset_fov": self._offset.get(device_id, [0.0, 0.0]),
        }

    # ---------------------------------------------------------------- tracking
    async def start_tracking(self, device_id: str, target: TrackingTarget,
                             params: TrackingParams | None = None) -> None:
        self.controller(device_id)  # validates PTZ availability
        vision = self.c.extensions.get("vision")
        if vision is None or device_id not in vision.engine.cameras:
            raise Unavailable("vision analysis is not active for this camera")
        await self.stop_tracking(device_id)
        rt = self.c.devices.get(device_id)
        settings: dict[str, Any] = dict(((rt.settings if rt else {}) or {}).get("ptz_tracking") or {})  # type: ignore[call-overload]
        state = TrackingState(target=target, params=params or TrackingParams(**settings))
        queue: asyncio.Queue[tuple[float, list[Track]]] = asyncio.Queue(maxsize=2)

        def on_tracks(_: str, t: float, tracks: list[Track], size: tuple[int, int]) -> None:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait((t, list(tracks)))

        unsubscribe = vision.engine.subscribe_tracks(device_id, on_tracks)
        session = TrackingSession(device_id, state, unsubscribe, queue)
        session.task = asyncio.create_task(self._track_loop(session), name=f"ptz-track:{device_id}")
        self.tracking[device_id] = session
        await self._event(device_id, "ptz.tracking.started", {"target": target.value or target.kind})

    async def stop_tracking(self, device_id: str) -> bool:
        session = self.tracking.pop(device_id, None)
        if session is None:
            return False
        session.unsubscribe()
        if session.task:
            session.task.cancel()
        await self._event(device_id, "ptz.tracking.stopped", {})
        return True

    async def _track_loop(self, session: TrackingSession) -> None:
        while True:
            try:
                _, tracks = await asyncio.wait_for(session.queue.get(), timeout=2.0)
            except TimeoutError:
                tracks = []
            session.state.paused_until = max(session.state.paused_until,
                                             self._manual_until.get(session.device_id, 0.0))
            command: Command | None = step(session.state, tracks, time.monotonic())
            if command is None:
                continue
            try:
                if command.kind == "home":
                    await self.home(session.device_id)
                else:
                    await self.move(session.device_id, command.pan, command.tilt, manual=False)
            except Exception as exc:
                log.warning("ptz tracking command failed", device=session.device_id, error=str(exc))

    async def scan(self, device_id: str, label: str, *, steps: int = 6, settle_s: float = 2.5) -> dict[str, Any]:
        """Systematic visual search: visit presets (or pan steps) and run the detector."""
        vision = self.c.extensions.get("vision")
        if vision is None:
            raise Unavailable("vision not available")
        if device_id in self.tracking:
            await self.stop_tracking(device_id)
        presets = await self.presets(device_id)
        found: list[dict[str, Any]] = []
        positions: list[str] = []
        if presets:
            for preset in presets[:steps]:
                await self.goto_preset(device_id, preset.id, manual=False)
                positions.append(preset.name)
                await asyncio.sleep(settle_s)
                result = await vision.engine.analyze_device(device_id)
                hits = [d for d in result["detections"] if d.label == label]
                if hits:
                    found.append({"position": preset.name, "count": len(hits),
                                  "score": round(max(d.score for d in hits), 2)})
        else:
            step_size = 0.8  # most of one field of view per step
            await self.home(device_id)
            await asyncio.sleep(settle_s)
            for i in range(steps):
                direction = step_size if i < steps // 2 else -step_size
                if i == steps // 2:
                    await self.home(device_id)
                    await asyncio.sleep(settle_s)
                await self.move(device_id, direction, 0.0, manual=False)
                positions.append(f"{'rechts' if direction > 0 else 'links'} {i % (steps // 2) + 1}")
                await asyncio.sleep(settle_s)
                result = await vision.engine.analyze_device(device_id)
                hits = [d for d in result["detections"] if d.label == label]
                if hits:
                    found.append({"position": positions[-1], "count": len(hits),
                                  "score": round(max(d.score for d in hits), 2)})
                    break
        return {"label": label, "visited": positions, "found": found}

    async def _event(self, device_id: str, type: str, payload: dict[str, Any]) -> None:
        rt = self.c.devices.get(device_id)
        await self.c.bus.publish(Event(type=type, payload={"device_id": device_id, **payload},
                                       source=EventSource(kind="device", device_id=device_id,
                                                          room_id=rt.room_id if rt else None)))

    async def stop_all(self) -> None:
        for device_id in list(self.tracking):
            await self.stop_tracking(device_id)

    def require_device(self, device_id: str) -> None:
        if self.c.devices.get(device_id) is None:
            raise NotFound("device not active")
