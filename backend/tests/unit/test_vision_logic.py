import numpy as np
from justai_sdk.ports.vision import BBox, Detection

from justai.vision.engine import _point_in_polygon
from justai.vision.frames import MotionDetector, apply_privacy_mask
from justai.vision.states import classify, features
from justai.vision.tracker import IouTracker


def det(label: str, x: float, y: float, w: float = 0.2, h: float = 0.4, score: float = 0.8) -> Detection:
    return Detection(label=label, score=score, bbox=BBox(x=x, y=y, w=w, h=h))


def test_tracker_confirms_after_two_hits_and_reports_leaving() -> None:
    tr = IouTracker(min_hits=2, max_age_s=2.0)
    appeared, left = tr.update([det("person", 0.1, 0.1)], 0.0)
    assert not appeared
    appeared, _ = tr.update([det("person", 0.12, 0.1)], 0.5)
    assert len(appeared) == 1 and appeared[0].label == "person"
    track_id = appeared[0].id
    appeared, left = tr.update([det("person", 0.15, 0.1)], 1.0)
    assert not appeared and not left
    _, left = tr.update([], 3.5)
    assert [t.id for t in left] == [track_id]


def test_tracker_keeps_classes_apart() -> None:
    tr = IouTracker(min_hits=1)
    tr.update([det("person", 0.1, 0.1), det("dog", 0.1, 0.1)], 0.0)
    assert len(tr.tracks) == 2


def test_privacy_mask_blackens_zone() -> None:
    img = np.full((100, 200, 3), 255, np.uint8)
    out = apply_privacy_mask(img, [[(0.0, 0.0), (0.5, 0.0), (0.5, 0.5), (0.0, 0.5)]])
    assert out[10, 10].sum() == 0
    assert out[90, 190].sum() == 255 * 3
    assert img[10, 10].sum() == 255 * 3  # input untouched


def test_motion_detector_start_and_end() -> None:
    md = MotionDetector(quiet_s=1.0)
    still = np.zeros((90, 160, 3), np.uint8)
    assert md.update(still, 0.0) is None
    assert md.update(still, 0.5) is None
    moving = still.copy()
    moving[20:60, 40:100] = 255
    assert md.update(moving, 1.0) is True
    # A static scene change is absorbed into the background; motion ends after quiet_s.
    results = [md.update(moving, 1.5 + i * 0.5) for i in range(20)]
    assert False in results


def test_point_in_polygon() -> None:
    square = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert _point_in_polygon((0.5, 0.5), square)
    assert not _point_in_polygon((1.5, 0.5), square)


def test_state_detector_classifies_open_and_closed() -> None:
    rng = np.random.default_rng(0)
    background = rng.integers(60, 120, (120, 160, 3), dtype=np.uint8)
    closed = background.copy()
    closed[20:100, 40:120] = (90, 90, 90)  # door panel
    opened = background.copy()
    opened[20:100, 40:120] = (15, 15, 15)  # dark opening
    opened[20:35, 40:120] = (200, 200, 200)  # rolled-up door at the top
    zone = {"x": 0.2, "y": 0.1, "w": 0.6, "h": 0.8}
    refs = {"geschlossen": [features(closed, zone)], "offen": [features(opened, zone)]}
    noisy_open = np.clip(opened.astype(int) + rng.integers(-12, 12, opened.shape), 0, 255).astype(np.uint8)
    brighter_closed = np.clip(closed.astype(int) + 35, 0, 255).astype(np.uint8)  # different light
    assert classify(features(noisy_open, zone), refs)[0] == "offen"
    assert classify(features(brighter_closed, zone), refs)[0] == "geschlossen"
