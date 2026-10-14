"""PTZ tracking controller (pure logic, unit-testable).

Keeps a target near the image centre with a dead zone, proportional steps and a
minimum interval between commands, so the camera does not jitter and the PTZ API
is not flooded. Lost targets are held for a while, then the camera returns home.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from justai.vision.tracker import Track


@dataclass
class TrackingParams:
    dead_zone: float = 0.12  # fraction of the image around the centre that needs no move
    gain: float = 0.8  # fraction of the offset corrected per command
    max_step: float = 0.35  # max FOV fraction per command
    min_interval_s: float = 1.2  # cameras like Tapo need time to settle
    lost_hold_s: float = 6.0  # keep position after the target disappeared
    return_home_after_s: float = 30.0
    tilt_enabled: bool = True


@dataclass
class TrackingTarget:
    kind: str = "person"  # person | label | person_id
    value: str | None = None  # label or person id


@dataclass
class TrackingState:
    target: TrackingTarget
    params: TrackingParams = field(default_factory=TrackingParams)
    current_track: str | None = None
    last_command: float = float("-inf")
    last_seen: float | None = None
    lost_since: float | None = None
    returned_home: bool = False
    paused_until: float = 0.0  # manual override
    state: str = "searching"  # searching | following | holding | home | paused


@dataclass(frozen=True)
class Command:
    kind: str  # move | home
    pan: float = 0.0
    tilt: float = 0.0


def select_track(tracks: list[Track], target: TrackingTarget, current: str | None) -> Track | None:
    if target.kind == "person_id":
        candidates = [t for t in tracks if t.person_id == target.value]
    elif target.kind == "label":
        candidates = [t for t in tracks if t.label == target.value or t.entity_id == target.value]
    else:
        candidates = [t for t in tracks if t.label == "person"]
    if not candidates:
        return None
    for t in candidates:  # stick with the current target (no jumping between people)
        if t.id == current:
            return t
    return max(candidates, key=lambda t: t.bbox.area)


def step(state: TrackingState, tracks: list[Track], now: float) -> Command | None:
    p = state.params
    if now < state.paused_until:
        state.state = "paused"
        return None
    track = select_track(tracks, state.target, state.current_track)
    if track is None:
        if state.lost_since is None:
            # Measure from the last sighting, not from the first frame without the target.
            state.lost_since = state.last_seen if state.last_seen is not None else now
        lost_for = now - state.lost_since
        if lost_for >= p.return_home_after_s and not state.returned_home:
            state.returned_home = True
            state.state = "home"
            return Command("home")
        state.state = "holding" if lost_for < p.lost_hold_s else ("home" if state.returned_home else "searching")
        return None
    state.current_track = track.id
    state.lost_since = None
    state.returned_home = False
    state.last_seen = now
    state.state = "following"
    dx = track.bbox.cx - 0.5
    # Aim slightly above the box centre for people (head/upper body).
    dy = (track.bbox.y + track.bbox.h * (0.3 if track.label == "person" else 0.5)) - 0.5
    if abs(dx) < p.dead_zone / 2 and (not p.tilt_enabled or abs(dy) < p.dead_zone / 2):
        return None
    if now - state.last_command < p.min_interval_s:
        return None
    pan = max(-p.max_step, min(p.max_step, dx * p.gain)) if abs(dx) >= p.dead_zone / 2 else 0.0
    tilt = 0.0
    if p.tilt_enabled and abs(dy) >= p.dead_zone / 2:
        tilt = max(-p.max_step, min(p.max_step, -dy * p.gain))  # image y grows downward
    if pan == 0.0 and tilt == 0.0:
        return None
    state.last_command = now
    return Command("move", pan, tilt)
