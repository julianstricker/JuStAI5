"""Long-term memory: storage, semantic search, extraction, consolidation, forgetting.

Memory types: working memory is the session context (not stored here); *episodes*
summarise past conversations/events; *facts* and *preferences* are semantic
memory; *procedures* are learned behaviour (automations reference them).

Every memory has a provenance: ``confirmed`` (explicitly stated/confirmed by a
user), ``extracted`` (taken from a conversation), ``observed`` (vision/sensors),
``inferred`` (a model's guess - always labelled as such).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from justai_sdk.events import Event
from justai_sdk.ports.ai import ChatMessage, Role
from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, func, or_, select, update

from justai.ai.config import ModelRole
from justai.ai.router import AIRouter, DataFlags
from justai.common.errors import NotFound
from justai.db.engine import Database
from justai.db.models import MEMORY_EMBEDDING_DIM, ConversationSession, Memory, Person, TranscriptTurn
from justai.events.bus import EventBus
from justai.logging import get_logger

log = get_logger(__name__)

DUPLICATE_SIMILARITY = 0.92


class Provenance(StrEnum):
    CONFIRMED = "confirmed"
    EXTRACTED = "extracted"
    OBSERVED = "observed"
    INFERRED = "inferred"


PROVENANCE_RANK = {Provenance.CONFIRMED: 3, Provenance.OBSERVED: 2, Provenance.EXTRACTED: 1,
                   Provenance.INFERRED: 0}


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)
    kind: str = "fact"  # fact | preference | episode | procedure | note
    scope: str = "shared"  # private | room | shared | system
    owner_person_id: str | None = None
    room_id: str | None = None
    subject: str | None = None
    predicate: str | None = None
    value: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance = Provenance.CONFIRMED
    confidence: float = Field(0.9, ge=0, le=1)
    importance: float = Field(0.5, ge=0, le=1)
    source: dict[str, Any] = Field(default_factory=dict)


class MemoryPatch(BaseModel):
    content: str | None = None
    kind: str | None = None
    scope: str | None = None
    owner_person_id: str | None = None
    subject: str | None = None
    predicate: str | None = None
    value: dict[str, Any] | None = None
    confidence: float | None = None
    importance: float | None = None


class MemoryHit(BaseModel):
    id: str
    kind: str
    scope: str
    owner_person_id: str | None
    room_id: str | None
    subject: str | None
    predicate: str | None
    content: str
    value: dict[str, Any]
    provenance: str
    confidence: float
    importance: float
    source: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime
    score: float | None = None


def _same_owner(owner: str | None) -> Any:
    """SQL condition matching the owner (NULL-safe)."""
    return Memory.owner_person_id.is_(None) if owner is None else Memory.owner_person_id == owner


def _hit(m: Memory, score: float | None = None) -> MemoryHit:
    return MemoryHit(id=m.id, kind=m.kind, scope=m.scope, owner_person_id=m.owner_person_id,
                     room_id=m.room_id, subject=m.subject, predicate=m.predicate, content=m.content,
                     value=m.value or {}, provenance=m.provenance, confidence=m.confidence,
                     importance=m.importance, source=m.source or {}, status=m.status,
                     created_at=m.created_at, updated_at=m.updated_at, score=score)


EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Self-contained fact in German"},
                    "kind": {"type": "string", "enum": ["fact", "preference", "episode", "procedure"]},
                    "about": {"type": "string", "description": "'speaker', 'household' or a person name"},
                    "subject": {"type": "string"},
                    "predicate": {"type": "string", "description": "snake_case relation, e.g. ordered_vehicle"},
                    "value": {"type": "object"},
                    "certainty": {"type": "string", "enum": ["stated", "implied", "guess"]},
                    "importance": {"type": "number"},
                    "private": {"type": "boolean"},
                },
                "required": ["content", "kind", "about", "certainty"],
            },
        },
        "summary": {"type": "string", "description": "One-sentence summary of the conversation"},
    },
    "required": ["memories"],
}

EXTRACTION_PROMPT = """Du extrahierst dauerhaft nützliche Erinnerungen aus einem Gespräch zwischen
einem Hausassistenten und Menschen. Speichere nur Dinge, die später hilfreich sind: Fakten über
Personen, Besitz, Pläne, Vorlieben, Gewohnheiten, Beziehungen, wichtige Ereignisse.
Speichere KEINE Smalltalk-Inhalte, Fragen nach Uhrzeit/Wetter, Tool-Ergebnisse oder
Aussagen des Assistenten über sich selbst.
- certainty: "stated" wenn der Benutzer es ausdrücklich gesagt hat, "implied" wenn es klar
  folgt, "guess" bei Vermutungen.
- about: "speaker" wenn es den Sprecher betrifft, sonst Name der Person oder "household".
- private: true für persönliche/sensible Informationen.
Antworte als JSON nach Schema. Wenn nichts zu speichern ist: {"memories": []}."""


class MemoryService:
    def __init__(self, db: Database, ai: AIRouter, bus: EventBus) -> None:
        self.db = db
        self.ai = ai
        self.bus = bus

    # ------------------------------------------------------------------ helpers
    async def _embed(self, text: str, kind: str = "document") -> tuple[list[float] | None, str | None]:
        try:
            vectors, model = await self.ai.embed([text], kind=kind)
        except Exception as exc:
            log.warning("embedding unavailable; memory stored without vector", error=str(exc))
            return None, None
        vec = vectors[0]
        if len(vec) != MEMORY_EMBEDDING_DIM:
            log.warning("embedding dimension mismatch", got=len(vec), expected=MEMORY_EMBEDDING_DIM)
            return None, model
        return vec, model

    @staticmethod
    def _visible(person_id: str | None, room_id: str | None, scopes: tuple[str, ...]) -> Any:
        clauses = []
        if "private" in scopes and person_id:
            clauses.append(and_(Memory.scope == "private", Memory.owner_person_id == person_id))
        if "room" in scopes:
            clauses.append(and_(Memory.scope == "room",
                                or_(Memory.room_id == room_id, Memory.room_id.is_(None))))
        for scope in ("shared", "system"):
            if scope in scopes:
                clauses.append(Memory.scope == scope)
        return or_(*clauses) if clauses else Memory.id.is_(None)

    # ---------------------------------------------------------------------- CRUD
    async def add(self, data: MemoryIn, *, dedupe: bool = True) -> MemoryHit:
        vec, model = await self._embed(data.content)
        async with self.db.session() as s:
            if dedupe and vec is not None:
                dist = Memory.embedding.cosine_distance(vec)
                stmt = (select(Memory, dist.label("d")).where(
                    Memory.status == "active", Memory.embedding.is_not(None),
                    _same_owner(data.owner_person_id)).order_by(dist).limit(1))
                row = (await s.execute(stmt)).first()
                if row is not None and 1 - float(row.d) >= DUPLICATE_SIMILARITY:
                    existing: Memory = row.Memory
                    if PROVENANCE_RANK[data.provenance] >= PROVENANCE_RANK[Provenance(existing.provenance)]:
                        existing.content = data.content
                        existing.provenance = data.provenance
                        existing.embedding = vec
                    existing.confidence = max(existing.confidence, data.confidence)
                    existing.importance = max(existing.importance, data.importance)
                    existing.source = {**(existing.source or {}), "reinforced_by": data.source}
                    existing.updated_at = datetime.now(UTC)
                    return _hit(existing, 1 - float(row.d))
            memory = Memory(kind=data.kind, scope=data.scope, owner_person_id=data.owner_person_id,
                            room_id=data.room_id, subject=data.subject, predicate=data.predicate,
                            content=data.content, value=data.value, provenance=data.provenance,
                            confidence=data.confidence, importance=data.importance,
                            source=data.source, embedding=vec, embedding_model=model)
            s.add(memory)
            await s.flush()
            # Contradiction handling: same subject + predicate -> newer fact supersedes.
            if data.subject and data.predicate:
                await s.execute(update(Memory).where(
                    Memory.id != memory.id, Memory.status == "active",
                    Memory.subject == data.subject, Memory.predicate == data.predicate,
                    _same_owner(data.owner_person_id),
                ).values(status="superseded", superseded_by=memory.id))
            hit = _hit(memory)
        await self.bus.publish(Event(type="memory.created", payload={
            "memory_id": hit.id, "kind": hit.kind, "provenance": hit.provenance,
            "person_id": hit.owner_person_id}))
        return hit

    async def get(self, memory_id: str) -> MemoryHit:
        async with self.db.session() as s:
            m = await s.get(Memory, memory_id)
        if m is None:
            raise NotFound("memory not found")
        return _hit(m)

    async def update(self, memory_id: str, patch: MemoryPatch) -> MemoryHit:
        vec: list[float] | None = None
        if patch.content is not None:
            vec, _ = await self._embed(patch.content)
        async with self.db.session() as s:
            m = await s.get(Memory, memory_id)
            if m is None:
                raise NotFound("memory not found")
            for field, value in patch.model_dump(exclude_unset=True).items():
                setattr(m, field, value)
            if vec is not None:
                m.embedding = vec
            if patch.content is not None:
                m.provenance = Provenance.CONFIRMED  # edited by a human
            return _hit(m)

    async def delete(self, memory_id: str) -> None:
        async with self.db.session() as s:
            result = await s.execute(delete(Memory).where(Memory.id == memory_id))
            if not result.rowcount:  # type: ignore[attr-defined]
                raise NotFound("memory not found")

    # -------------------------------------------------------------------- search
    async def search(self, query: str, *, person_id: str | None = None, room_id: str | None = None,
                     limit: int = 10, scopes: tuple[str, ...] = ("private", "room", "shared", "system"),
                     kind: str | None = None, include_inactive: bool = False,
                     owner_filter: str | None = None) -> list[MemoryHit]:
        visible = self._visible(person_id, room_id, scopes)
        filters = [visible]
        if not include_inactive:
            filters.append(Memory.status == "active")
        if kind:
            filters.append(Memory.kind == kind)
        if owner_filter:
            filters.append(Memory.owner_person_id == owner_filter)
        async with self.db.session() as s:
            hits: list[MemoryHit] = []
            if query.strip():
                vec, _ = await self._embed(query, kind="query")
                if vec is not None:
                    dist = Memory.embedding.cosine_distance(vec)
                    rows = (await s.execute(select(Memory, dist.label("d")).where(
                        *filters, Memory.embedding.is_not(None)).order_by(dist).limit(limit))).all()
                    hits = [_hit(r.Memory, 1 - float(r.d)) for r in rows if 1 - float(r.d) > 0.25]
                if len(hits) < limit:
                    seen = {h.id for h in hits}
                    words = [w for w in query.split() if len(w) > 3][:5]
                    if words:
                        kw = or_(*[Memory.content.ilike(f"%{w}%") for w in words])
                        rows2 = (await s.scalars(select(Memory).where(*filters, kw)
                                                 .limit(limit))).all()
                        hits += [_hit(m, None) for m in rows2 if m.id not in seen][: limit - len(hits)]
            else:
                rows3 = (await s.scalars(select(Memory).where(*filters).order_by(
                    Memory.importance.desc(), Memory.updated_at.desc()).limit(limit))).all()
                hits = [_hit(m) for m in rows3]
            if hits:
                await s.execute(update(Memory).where(Memory.id.in_([h.id for h in hits])).values(
                    access_count=Memory.access_count + 1, last_accessed_at=func.now()))
        return hits

    async def recall(self, query: str, *, person_id: str | None, room_id: str | None,
                     limit: int = 6) -> list[str]:
        """Memories formatted for a prompt (only what the speaker may see)."""
        hits = await self.search(query, person_id=person_id, room_id=room_id, limit=limit)
        if person_id and not query:
            about = await self.search("", person_id=person_id, room_id=room_id, limit=limit,
                                      owner_filter=person_id)
            known = {h.id for h in hits}
            hits = [*about, *[h for h in hits if h.id not in known]][:limit]
        out = []
        for h in hits:
            label = {"confirmed": "bestätigt", "extracted": "aus Gespräch",
                     "observed": "beobachtet", "inferred": "VERMUTUNG"}.get(h.provenance, h.provenance)
            out.append(f"[{label}, {h.updated_at:%d.%m.%Y}] {h.content}")
        return out

    async def list_all(self, *, person_id: str | None = None, kind: str | None = None,
                       limit: int = 200) -> list[MemoryHit]:
        stmt = select(Memory).order_by(Memory.updated_at.desc()).limit(limit)
        if person_id:
            stmt = stmt.where(Memory.owner_person_id == person_id)
        if kind:
            stmt = stmt.where(Memory.kind == kind)
        async with self.db.session() as s:
            return [_hit(m) for m in (await s.scalars(stmt)).all()]

    # ---------------------------------------------------------------- extraction
    async def extract_from_session(self, session_id: str) -> int:
        async with self.db.session() as s:
            session = await s.get(ConversationSession, session_id)
            if session is None or session.memory_processed:
                return 0
            turns = (await s.scalars(select(TranscriptTurn).where(
                TranscriptTurn.session_id == session_id,
                TranscriptTurn.role.in_(["user", "assistant"])).order_by(TranscriptTurn.created_at))).all()
            speaker = await s.get(Person, session.person_id) if session.person_id else None
            people = {p.name.lower(): p.id for p in (await s.scalars(select(Person))).all()}
            person_id, room_id = session.person_id, session.room_id
        user_turns = [t for t in turns if t.role == "user"]
        if not user_turns or sum(len(t.text) for t in user_turns) < 15:
            await self._mark_processed(session_id)
            return 0
        transcript = "\n".join(f"{'Benutzer' if t.role == 'user' else 'Assistent'}: {t.text}"
                               for t in turns)
        speaker_line = f"Der Sprecher ist {speaker.name}." if speaker else "Der Sprecher ist unbekannt."
        result = await self.ai.chat(
            ModelRole.MEMORY,
            [ChatMessage(role=Role.SYSTEM, content=EXTRACTION_PROMPT),
             ChatMessage(role=Role.USER, content=f"{speaker_line}\n\nGespräch:\n{transcript}")],
            json_schema=EXTRACTION_SCHEMA, flags=DataFlags(personal=True), temperature=0.1)
        try:
            data = json.loads(result.text or "{}")
        except json.JSONDecodeError:
            log.warning("memory extraction returned invalid JSON", session=session_id)
            data = {"memories": []}
        stored = 0
        for item in data.get("memories", [])[:20]:
            about = str(item.get("about", "speaker")).lower()
            owner = person_id if about == "speaker" else people.get(about)
            if about == "speaker" and owner is None:
                owner = None  # unknown speaker: keep as shared household knowledge
            certainty = item.get("certainty", "implied")
            provenance = {"stated": Provenance.EXTRACTED, "implied": Provenance.EXTRACTED,
                          "guess": Provenance.INFERRED}.get(certainty, Provenance.EXTRACTED)
            confidence = {"stated": 0.9, "implied": 0.7, "guess": 0.4}.get(certainty, 0.6)
            private = bool(item.get("private")) and owner is not None
            await self.add(MemoryIn(
                content=str(item["content"])[:2000], kind=item.get("kind", "fact"),
                scope="private" if private else "shared", owner_person_id=owner, room_id=room_id,
                subject=item.get("subject") or (speaker.name if speaker and about == "speaker" else None),
                predicate=item.get("predicate"), value=item.get("value") or {},
                provenance=provenance, confidence=confidence,
                importance=float(item.get("importance") or 0.5),
                source={"type": "conversation", "session_id": session_id}))
            stored += 1
        summary = data.get("summary")
        if summary and stored:
            await self.add(MemoryIn(content=f"Gespräch: {summary}", kind="episode",
                                    scope="private" if person_id else "shared",
                                    owner_person_id=person_id, room_id=room_id,
                                    provenance=Provenance.EXTRACTED, confidence=0.8, importance=0.3,
                                    source={"type": "conversation", "session_id": session_id}),
                           dedupe=False)
        await self._mark_processed(session_id)
        log.info("memories extracted", session=session_id, count=stored)
        return stored

    async def _mark_processed(self, session_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(update(ConversationSession).where(ConversationSession.id == session_id)
                            .values(memory_processed=True))

    # ------------------------------------------------------------- consolidation
    async def consolidate(self, *, inferred_ttl_days: int = 90) -> dict[str, int]:
        merged = superseded = purged = 0
        async with self.db.session() as s:
            active = (await s.scalars(select(Memory).where(
                Memory.status == "active", Memory.embedding.is_not(None)))).all()
            removed: set[str] = set()
            for m in active:
                if m.id in removed:
                    continue
                dist = Memory.embedding.cosine_distance(m.embedding)
                rows = (await s.execute(select(Memory.id, dist.label("d")).where(
                    Memory.id != m.id, Memory.status == "active",
                    _same_owner(m.owner_person_id),
                    dist < 1 - DUPLICATE_SIMILARITY))).all()
                for row in rows:
                    if row.id in removed:
                        continue
                    other = await s.get(Memory, row.id)
                    if other is None:
                        continue
                    keep, drop = (m, other) if (PROVENANCE_RANK[Provenance(m.provenance)], m.updated_at) >= (
                        PROVENANCE_RANK[Provenance(other.provenance)], other.updated_at) else (other, m)
                    keep.confidence = max(keep.confidence, drop.confidence)
                    keep.importance = max(keep.importance, drop.importance)
                    keep.access_count += drop.access_count
                    removed.add(drop.id)
                    await s.delete(drop)
                    merged += 1
            # Conflicting facts (same subject/predicate/owner): keep the newest active one.
            groups = (await s.execute(select(Memory.subject, Memory.predicate, Memory.owner_person_id,
                                             func.count()).where(
                Memory.status == "active", Memory.subject.is_not(None), Memory.predicate.is_not(None))
                .group_by(Memory.subject, Memory.predicate, Memory.owner_person_id)
                .having(func.count() > 1))).all()
            for subj, pred, owner, _ in groups:
                items = (await s.scalars(select(Memory).where(
                    Memory.status == "active", Memory.subject == subj, Memory.predicate == pred,
                    _same_owner(owner))
                    .order_by(Memory.updated_at.desc()))).all()
                for old in items[1:]:
                    old.status, old.superseded_by = "superseded", items[0].id
                    superseded += 1
            cutoff = datetime.now(UTC) - timedelta(days=inferred_ttl_days)
            res = await s.execute(delete(Memory).where(
                Memory.provenance == Provenance.INFERRED, Memory.updated_at < cutoff,
                Memory.access_count == 0))
            purged = int(res.rowcount or 0)  # type: ignore[attr-defined]
        return {"merged": merged, "superseded": superseded, "purged": purged}

    async def merge_person(self, from_id: str, into_id: str) -> None:
        async with self.db.session() as s:
            await s.execute(update(Memory).where(Memory.owner_person_id == from_id)
                            .values(owner_person_id=into_id))
