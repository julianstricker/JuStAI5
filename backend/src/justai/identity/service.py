"""People, pets and biometric face profiles.

* Face embeddings are only stored with explicit consent (recorded with evidence).
* Recognition reports a *cosine similarity* and a match level (strong/weak); this
  is not a calibrated probability and is never presented as one.
* Revoking consent or deleting a person removes all biometric data.
* Biometrics never grant administrative permissions (see auth/rbac.py).
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import cv2
import numpy as np
from justai_sdk.events import Event
from justai_sdk.ports.vision import FaceAnalyzer, FaceObservation
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from justai.common.errors import Conflict, NotFound, ValidationFailed
from justai.db.engine import Database
from justai.db.models import Automation, Consent, FaceEmbedding, Person, Sighting, User
from justai.events.bus import EventBus
from justai.logging import get_logger

log = get_logger(__name__)

MIN_FACE_PX = 70
MIN_SHARPNESS = 40.0
MIN_FRONTAL = 0.55


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    kind: str = Field("person", pattern="^(person|pet)$")
    species: str | None = None
    notes: str = ""
    recognition_enabled: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)


class PersonPatch(BaseModel):
    name: str | None = None
    kind: str | None = Field(None, pattern="^(person|pet)$")
    species: str | None = None
    notes: str | None = None
    recognition_enabled: bool | None = None
    attributes: dict[str, Any] | None = None


@dataclass(frozen=True)
class Match:
    person_id: str
    name: str
    similarity: float
    level: str  # strong | weak


@dataclass
class EnrollResult:
    added: int
    rejected: int
    reasons: list[str]


def quality_issues(face: FaceObservation) -> list[str]:
    issues = []
    if face.size_px < MIN_FACE_PX:
        issues.append(f"Gesicht zu klein ({face.size_px}px < {MIN_FACE_PX}px)")
    if face.sharpness < MIN_SHARPNESS:
        issues.append("Bild unscharf")
    if not 40 <= face.brightness <= 225:
        issues.append("zu dunkel oder zu hell")
    if face.frontalness < MIN_FRONTAL:
        issues.append("Gesicht nicht frontal genug")
    return issues


class IdentityService:
    def __init__(self, db: Database, bus: EventBus) -> None:
        self.db = db
        self.bus = bus
        self._gallery: list[tuple[str, str, np.ndarray]] = []  # (person_id, name, matrix)
        self.store_thumbnails = True

    # --------------------------------------------------------------- gallery
    async def reload_gallery(self) -> None:
        async with self.db.session() as s:
            people = (await s.scalars(select(Person).where(
                Person.biometric_consent, Person.recognition_enabled, Person.merged_into.is_(None)))).all()
            rows = (await s.scalars(select(FaceEmbedding))).all()
        by_person: dict[str, list[np.ndarray]] = {}
        for r in rows:
            by_person.setdefault(r.person_id, []).append(np.asarray(r.embedding, dtype=np.float32))
        self._gallery = [(p.id, p.name, np.stack(by_person[p.id])) for p in people if p.id in by_person]

    def match(self, embedding: np.ndarray, analyzer: FaceAnalyzer) -> Match | None:
        best: Match | None = None
        for person_id, name, matrix in self._gallery:
            sims = matrix @ embedding
            # Robust score: mean of the top-3 similarities of this person's gallery.
            top = np.sort(sims)[-3:]
            sim = float(top.mean())
            if best is None or sim > best.similarity:
                level = "strong" if sim >= analyzer.strong_match_threshold else "weak"
                best = Match(person_id, name, sim, level)
        if best is None or best.similarity < analyzer.match_threshold:
            return None
        return best

    # ----------------------------------------------------------------- people
    async def list(self) -> list[dict[str, Any]]:
        async with self.db.session() as s:
            people = (await s.scalars(select(Person).where(Person.merged_into.is_(None))
                                      .order_by(Person.name))).all()
            counts = dict((await s.execute(select(FaceEmbedding.person_id, func.count())
                                           .group_by(FaceEmbedding.person_id))).all())
            last = {}
            for row in (await s.execute(select(Sighting.person_id, func.max(Sighting.last_seen))
                                        .where(Sighting.person_id.is_not(None))
                                        .group_by(Sighting.person_id))).all():
                last[row[0]] = row[1]
        return [{"id": p.id, "name": p.name, "kind": p.kind, "species": p.species, "notes": p.notes,
                 "attributes": p.attributes, "biometric_consent": p.biometric_consent,
                 "biometric_consent_at": p.biometric_consent_at,
                 "recognition_enabled": p.recognition_enabled, "face_count": counts.get(p.id, 0),
                 "last_seen": {"at": last[p.id], "camera": None, "room": None} if p.id in last else None}
                for p in people]

    async def get(self, person_id: str) -> Person:
        async with self.db.session() as s:
            person = await s.get(Person, person_id)
        if person is None or person.merged_into:
            raise NotFound("person not found")
        return person

    async def find_by_name(self, name: str) -> Person | None:
        async with self.db.session() as s:
            return await s.scalar(select(Person).where(func.lower(Person.name) == name.strip().lower(),
                                                       Person.merged_into.is_(None)))

    async def create(self, data: PersonIn) -> Person:
        if await self.find_by_name(data.name):
            raise Conflict(f"'{data.name}' gibt es bereits")
        async with self.db.session() as s:
            person = Person(**data.model_dump())
            s.add(person)
        return person

    async def update(self, person_id: str, patch: PersonPatch) -> Person:
        async with self.db.session() as s:
            person = await s.get(Person, person_id)
            if person is None:
                raise NotFound("person not found")
            for k, v in patch.model_dump(exclude_unset=True).items():
                setattr(person, k, v)
        await self.reload_gallery()
        return person

    async def delete(self, person_id: str) -> None:
        async with self.db.session() as s:
            person = await s.get(Person, person_id)
            if person is None:
                raise NotFound("person not found")
            await s.delete(person)  # cascades to faces, consents, private memories
        await self.reload_gallery()

    # ---------------------------------------------------------------- consent
    async def set_consent(self, person_id: str, kind: str, granted: bool,
                          evidence: dict[str, Any]) -> None:
        async with self.db.session() as s:
            person = await s.get(Person, person_id)
            if person is None:
                raise NotFound("person not found")
            s.add(Consent(person_id=person_id, kind=kind, granted=granted, evidence=evidence))
            if kind == "face":
                person.biometric_consent = granted
                person.biometric_consent_at = datetime.now(UTC) if granted else None
                if not granted:
                    await s.execute(delete(FaceEmbedding).where(FaceEmbedding.person_id == person_id))
        await self.reload_gallery()

    # -------------------------------------------------------------- enrolment
    async def enroll_images(self, person_id: str, images: list[np.ndarray], analyzer: FaceAnalyzer,
                            *, source: str = "enrollment", max_samples: int = 8) -> EnrollResult:
        person = await self.get(person_id)
        if not person.biometric_consent:
            raise ValidationFailed("biometrische Registrierung erfordert eine Einwilligung")
        reasons: list[str] = []
        accepted: list[tuple[np.ndarray, FaceObservation, np.ndarray]] = []
        for image in images:
            faces = analyzer.detect_faces(image)
            if len(faces) != 1:
                reasons.append("kein Gesicht" if not faces else f"{len(faces)} Gesichter im Bild")
                continue
            issues = quality_issues(faces[0])
            if issues:
                reasons.extend(issues)
                continue
            emb = analyzer.embed(image, faces[0])
            # Skip near-identical samples (no information gain).
            if any(float(e @ emb) > 0.97 for e, _, _ in accepted):
                continue
            accepted.append((emb, faces[0], image))
            if len(accepted) >= max_samples:
                break
        async with self.db.session() as s:
            for emb, face, image in accepted:
                thumb = self._thumbnail(image, face) if self.store_thumbnails else None
                s.add(FaceEmbedding(person_id=person_id, model=analyzer.embedding_model,
                                    embedding=emb.tolist(), source=source, thumbnail=thumb,
                                    quality={"size_px": face.size_px,
                                             "sharpness": round(face.sharpness, 1),
                                             "brightness": round(face.brightness, 1),
                                             "frontalness": round(face.frontalness, 2),
                                             "score": round(face.score, 3)}))
        await self.reload_gallery()
        if accepted:
            await self.bus.publish(Event(type="identity.person.enrolled",
                                         payload={"person_id": person_id, "samples": len(accepted)}))
        unique_reasons = sorted(set(reasons))
        return EnrollResult(len(accepted), len(images) - len(accepted), unique_reasons)

    @staticmethod
    def _thumbnail(image: np.ndarray, face: FaceObservation) -> bytes:
        h, w = image.shape[:2]
        b = face.bbox
        pad = 0.25
        x0, y0 = int(max(0, (b.x - b.w * pad) * w)), int(max(0, (b.y - b.h * pad) * h))
        x1, y1 = int(min(w, (b.x + b.w * (1 + pad)) * w)), int(min(h, (b.y + b.h * (1 + pad)) * h))
        crop = cv2.resize(image[y0:y1, x0:x1], (96, 96))
        ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else b""

    async def faces(self, person_id: str) -> list[dict[str, Any]]:
        async with self.db.session() as s:
            rows = (await s.scalars(select(FaceEmbedding).where(FaceEmbedding.person_id == person_id)
                                    .order_by(FaceEmbedding.created_at))).all()
        return [{"id": r.id, "quality": r.quality, "source": r.source, "created_at": r.created_at,
                 "has_thumbnail": bool(r.thumbnail)} for r in rows]

    async def face_thumbnail(self, face_id: str) -> bytes:
        async with self.db.session() as s:
            row = await s.get(FaceEmbedding, face_id)
        if row is None or not row.thumbnail:
            raise NotFound("no thumbnail")
        return row.thumbnail

    async def delete_face(self, face_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(FaceEmbedding).where(FaceEmbedding.id == face_id))
        await self.reload_gallery()

    # ------------------------------------------------------- merge / export
    async def merge(self, from_id: str, into_id: str) -> None:
        if from_id == into_id:
            raise ValidationFailed("cannot merge a person into itself")
        await self.get(into_id)
        async with self.db.session() as s:
            source = await s.get(Person, from_id)
            if source is None:
                raise NotFound("person not found")
            await s.execute(update(FaceEmbedding).where(FaceEmbedding.person_id == from_id)
                            .values(person_id=into_id))
            await s.execute(update(Sighting).where(Sighting.person_id == from_id)
                            .values(person_id=into_id))
            await s.execute(update(Automation).where(Automation.owner_person_id == from_id)
                            .values(owner_person_id=into_id))
            await s.execute(update(User).where(User.person_id == from_id).values(person_id=into_id))
            source.merged_into = into_id
            source.recognition_enabled = False
        await self.reload_gallery()

    async def export(self, person_id: str) -> dict[str, Any]:
        """Data export (GDPR art. 15/20): profile, consents, biometric data, sightings."""
        person = await self.get(person_id)
        async with self.db.session() as s:
            consents = (await s.scalars(select(Consent).where(Consent.person_id == person_id))).all()
            faces = (await s.scalars(select(FaceEmbedding).where(FaceEmbedding.person_id == person_id))).all()
            sightings = (await s.scalars(select(Sighting).where(Sighting.person_id == person_id)
                                         .order_by(Sighting.last_seen.desc()).limit(1000))).all()
        return {
            "person": {"id": person.id, "name": person.name, "kind": person.kind,
                       "species": person.species, "notes": person.notes,
                       "attributes": person.attributes, "biometric_consent": person.biometric_consent},
            "consents": [{"kind": c.kind, "granted": c.granted, "ts": c.ts.isoformat(),
                          "evidence": c.evidence} for c in consents],
            "face_embeddings": [{"id": f.id, "model": f.model, "created_at": f.created_at.isoformat(),
                                 "quality": f.quality, "embedding": list(map(float, f.embedding)),
                                 "thumbnail_jpeg_base64": base64.b64encode(f.thumbnail).decode()
                                 if f.thumbnail else None} for f in faces],
            "sightings": [{"camera": x.camera_device_id, "room": x.room_id, "first_seen": x.first_seen.isoformat(),
                           "last_seen": x.last_seen.isoformat()} for x in sightings],
        }

    async def pets_by_species(self) -> dict[str, list[Person]]:
        async with self.db.session() as s:
            pets = (await s.scalars(select(Person).where(Person.kind == "pet",
                                                         Person.merged_into.is_(None)))).all()
        out: dict[str, list[Person]] = {}
        for p in pets:
            if p.species:
                out.setdefault(p.species.lower(), []).append(p)
        return out
