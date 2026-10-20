"""Voice profiles: recognise who is speaking (with consent only).

* Samples are speaker embeddings (WeSpeaker ResNet34), computed from speech of a
  conversation in which the person agreed (consent kind "voice"). No audio is stored.
* Recognition compares a new utterance (e.g. the wake phrase) with every profile and
  only names a person if the match is clear: similarity above IDENTIFY_SIMILARITY and
  a margin to the next person. It is a cosine similarity, not a probability.
* Revoking the voice consent or deleting the person removes all samples.
* Like face recognition, a recognised voice personalises the conversation but never
  grants administrative permissions (auth/rbac.py).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import numpy as np
from sqlalchemy import delete, func, select

from justai.audio.dsp import SR
from justai.audio.speaker import SpeakerEmbedder
from justai.common.errors import NotFound, ValidationFailed
from justai.db.engine import Database
from justai.db.models import Consent, Person, VoiceEmbedding
from justai.logging import get_logger

log = get_logger(__name__)

MODEL_ID = "wespeaker-resnet34"
# Tests: same speaker 0.68-0.82 (wake phrase vs. conversation), other speakers 0.26-0.38.
IDENTIFY_SIMILARITY = 0.55
IDENTIFY_MARGIN = 0.08
MIN_ENROLL_SECONDS = 4.0
MAX_SAMPLES = 10
SEGMENT_SECONDS = 4.0


@dataclass(frozen=True)
class VoiceMatch:
    person_id: str
    name: str
    similarity: float
    margin: float


class VoiceProfiles:
    def __init__(self, db: Database, embedder: SpeakerEmbedder) -> None:
        self.db = db
        self.embedder = embedder
        self._gallery: list[tuple[str, str, np.ndarray]] = []

    # --------------------------------------------------------------- gallery
    async def reload(self) -> None:
        async with self.db.session() as s:
            rows = (await s.execute(
                select(VoiceEmbedding.person_id, Person.name, VoiceEmbedding.embedding)
                .join(Person, Person.id == VoiceEmbedding.person_id)
                .where(Person.recognition_enabled, Person.merged_into.is_(None)))).all()
        by_person: dict[str, tuple[str, list[np.ndarray]]] = {}
        for person_id, name, emb in rows:
            by_person.setdefault(person_id, (name, []))[1].append(np.asarray(emb, np.float32))
        self._gallery = [(pid, name, np.stack(embs)) for pid, (name, embs) in by_person.items()]

    @property
    def enrolled(self) -> int:
        return len(self._gallery)

    def match(self, embedding: np.ndarray) -> VoiceMatch | None:
        scores: list[tuple[float, str, str]] = []
        for person_id, name, matrix in self._gallery:
            sims = matrix @ embedding
            scores.append((float(np.sort(sims)[-3:].mean()), person_id, name))
        if not scores:
            return None
        scores.sort(reverse=True)
        best, runner_up = scores[0], (scores[1][0] if len(scores) > 1 else -1.0)
        margin = best[0] - runner_up
        if best[0] < IDENTIFY_SIMILARITY or margin < IDENTIFY_MARGIN:
            return None
        return VoiceMatch(best[1], best[2], round(best[0], 3), round(margin, 3))

    async def identify(self, pcm16k: np.ndarray) -> VoiceMatch | None:
        if not self._gallery:
            return None
        emb = await asyncio.to_thread(self.embedder.embed, pcm16k)
        return self.match(emb) if emb is not None else None

    # ---------------------------------------------------------------- consent
    async def has_consent(self, person_id: str) -> bool:
        async with self.db.session() as s:
            granted = await s.scalar(select(Consent.granted).where(
                Consent.person_id == person_id, Consent.kind == "voice").order_by(Consent.ts.desc()).limit(1))
        return bool(granted)

    async def forget(self, person_id: str) -> int:
        async with self.db.session() as s:
            result = await s.execute(delete(VoiceEmbedding).where(VoiceEmbedding.person_id == person_id))
        await self.reload()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def counts(self) -> dict[str, int]:
        async with self.db.session() as s:
            rows = (await s.execute(select(VoiceEmbedding.person_id, func.count())
                                    .group_by(VoiceEmbedding.person_id))).all()
        return {pid: int(n) for pid, n in rows}

    # -------------------------------------------------------------- enrolment
    async def enroll(self, person_id: str, speech: list[np.ndarray], *, session_id: str | None,
                     source: str = "conversation") -> int:
        """Store voice samples from speech of the person; returns the number of samples added."""
        async with self.db.session() as s:
            if await s.get(Person, person_id) is None:
                raise NotFound("person not found")
        if not await self.has_consent(person_id):
            raise ValidationFailed("A voice profile requires consent")
        pcm = np.concatenate(speech) if speech else np.zeros(0, np.int16)
        if pcm.size < MIN_ENROLL_SECONDS * SR:
            raise ValidationFailed(f"too little speech ({pcm.size / SR:.1f} s, {MIN_ENROLL_SECONDS:.0f} s needed)")
        # Several samples from segments plus one from all speech: robust to short wake phrases.
        seg = int(SEGMENT_SECONDS * SR)
        pieces = [pcm[i:i + seg] for i in range(0, pcm.size - seg + 1, seg)] + [pcm]
        embeddings = [e for e in await asyncio.gather(*(asyncio.to_thread(self.embedder.embed, p) for p in pieces))
                      if e is not None]
        async with self.db.session() as s:
            for emb, piece in zip(embeddings, pieces, strict=False):
                s.add(VoiceEmbedding(person_id=person_id, model=MODEL_ID, embedding=emb.tolist(),
                                     seconds=round(piece.size / SR, 1), source=source, session_id=session_id))
            await s.flush()
            ids = (await s.scalars(select(VoiceEmbedding.id).where(VoiceEmbedding.person_id == person_id)
                                   .order_by(VoiceEmbedding.created_at.desc(), VoiceEmbedding.id.desc()))).all()
            if len(ids) > MAX_SAMPLES:  # keep the newest samples (voices change slowly)
                await s.execute(delete(VoiceEmbedding).where(VoiceEmbedding.id.in_(ids[MAX_SAMPLES:])))
        await self.reload()
        log.info("voice profile updated", person=person_id, samples=len(embeddings))
        return len(embeddings)
