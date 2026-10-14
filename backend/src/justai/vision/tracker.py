"""Lightweight multi-object tracker (greedy IoU matching per class, time based ageing)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from justai_sdk.ports.vision import BBox, Detection

_ids = itertools.count(1)


@dataclass
class Track:
    id: str
    label: str
    bbox: BBox
    score: float
    first_seen: float
    last_seen: float
    hits: int = 1
    best_score: float = 0.0
    confirmed: bool = False
    person_id: str | None = None
    person_name: str | None = None
    identity_similarity: float | None = None
    identity_votes: dict[str, int] = field(default_factory=dict)
    face_checks: int = 0
    last_face_check: float = 0.0
    entity_id: str | None = None  # e.g. a registered pet assumed for this track
    watches_fired: set[str] = field(default_factory=set)
    sighting_id: str | None = None
    last_persisted: float = 0.0

    @property
    def age_s(self) -> float:
        return self.last_seen - self.first_seen


class IouTracker:
    def __init__(self, *, iou_threshold: float = 0.25, min_hits: int = 2, max_age_s: float = 4.0,
                 smoothing: float = 0.6) -> None:
        self.iou_threshold = iou_threshold
        self.min_hits = min_hits
        self.max_age_s = max_age_s
        self.smoothing = smoothing
        self.tracks: dict[str, Track] = {}

    def update(self, detections: list[Detection], t: float) -> tuple[list[Track], list[Track]]:
        """Returns (newly confirmed tracks, tracks that left)."""
        appeared: list[Track] = []
        unmatched = list(range(len(detections)))
        pairs = sorted(
            ((d.bbox.iou(tr.bbox), i, tr.id) for i, d in enumerate(detections)
             for tr in self.tracks.values() if tr.label == d.label),
            reverse=True)
        used_tracks: set[str] = set()
        for iou, i, tid in pairs:
            if iou < self.iou_threshold:
                break
            if i not in unmatched or tid in used_tracks:
                continue
            tr = self.tracks[tid]
            det = detections[i]
            a = self.smoothing
            tr.bbox = BBox(x=a * det.bbox.x + (1 - a) * tr.bbox.x, y=a * det.bbox.y + (1 - a) * tr.bbox.y,
                           w=a * det.bbox.w + (1 - a) * tr.bbox.w, h=a * det.bbox.h + (1 - a) * tr.bbox.h)
            tr.score = det.score
            tr.best_score = max(tr.best_score, det.score)
            tr.last_seen = t
            tr.hits += 1
            if not tr.confirmed and tr.hits >= self.min_hits:
                tr.confirmed = True
                appeared.append(tr)
            unmatched.remove(i)
            used_tracks.add(tid)
        for i in unmatched:
            det = detections[i]
            tr = Track(id=f"trk-{next(_ids)}", label=det.label, bbox=det.bbox, score=det.score,
                       first_seen=t, last_seen=t, best_score=det.score)
            if self.min_hits <= 1:
                tr.confirmed = True
                appeared.append(tr)
            self.tracks[tr.id] = tr
        left = [tr for tr in self.tracks.values() if t - tr.last_seen > self.max_age_s]
        for tr in left:
            del self.tracks[tr.id]
        return appeared, [tr for tr in left if tr.confirmed]

    def confirmed(self) -> list[Track]:
        return [t for t in self.tracks.values() if t.confirmed]

    def clear(self) -> list[Track]:
        gone = self.confirmed()
        self.tracks.clear()
        return gone
