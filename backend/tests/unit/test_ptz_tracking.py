from justai_sdk.ports.vision import BBox

from justai.ptz.tracking import TrackingParams, TrackingState, TrackingTarget, step
from justai.vision.tracker import Track


def track(cx: float, cy: float = 0.5, label: str = "person", tid: str = "t1", area: float = 0.2,
          person_id: str | None = None) -> Track:
    w = h = area ** 0.5
    return Track(id=tid, label=label, bbox=BBox(x=cx - w / 2, y=cy - h * 0.3, w=w, h=h), score=0.9,
                 first_seen=0, last_seen=0, confirmed=True, person_id=person_id)


def state(**kw) -> TrackingState:  # type: ignore[no-untyped-def]
    return TrackingState(target=TrackingTarget(), params=TrackingParams(tilt_enabled=False, **kw))


def test_centered_target_needs_no_move() -> None:
    assert step(state(), [track(0.52)], 10.0) is None


def test_offset_target_moves_proportionally_and_limited() -> None:
    s = state()
    cmd = step(s, [track(0.8)], 10.0)
    assert cmd is not None and cmd.kind == "move" and 0 < cmd.pan <= 0.35
    s2 = state()
    cmd2 = step(s2, [track(0.99)], 10.0)
    assert cmd2 is not None and cmd2.pan == 0.35  # clamped


def test_rate_limit_between_commands() -> None:
    s = state(min_interval_s=1.0)
    assert step(s, [track(0.8)], 10.0) is not None
    assert step(s, [track(0.8)], 10.5) is None
    assert step(s, [track(0.8)], 11.1) is not None


def test_sticks_to_current_target_and_prefers_largest_initially() -> None:
    s = state()
    a, b = track(0.8, tid="a", area=0.05), track(0.2, tid="b", area=0.2)
    step(s, [a, b], 1.0)
    assert s.current_track == "b"
    b_grows_smaller = track(0.25, tid="b", area=0.01)
    step(s, [a, b_grows_smaller], 5.0)
    assert s.current_track == "b"


def test_lost_target_holds_then_returns_home_once() -> None:
    s = state(lost_hold_s=2, return_home_after_s=10)
    step(s, [track(0.5)], 0.0)
    assert step(s, [], 1.0) is None and s.state == "holding"
    assert step(s, [], 9.0) is None
    cmd = step(s, [], 10.5)
    assert cmd is not None and cmd.kind == "home"
    assert step(s, [], 30.0) is None  # only once


def test_manual_override_pauses_tracking() -> None:
    s = state()
    s.paused_until = 100.0
    assert step(s, [track(0.9)], 50.0) is None and s.state == "paused"


def test_person_id_target() -> None:
    s = TrackingState(target=TrackingTarget(kind="person_id", value="p-julian"),
                      params=TrackingParams(tilt_enabled=False))
    other = track(0.9, tid="x", area=0.3, person_id="p-anna")
    me = track(0.2, tid="y", area=0.05, person_id="p-julian")
    cmd = step(s, [other, me], 1.0)
    assert s.current_track == "y" and cmd is not None and cmd.pan < 0
