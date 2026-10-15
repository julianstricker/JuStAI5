"""Forgetting is permanent: automatic extraction from older transcripts must not
re-create a memory the user asked to forget (found in a live test, 2026-10-15)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest
from sqlalchemy import delete, select

from justai.db.engine import Database
from justai.db.models import ConversationSession, Memory, TranscriptTurn
from justai.memory.service import FORGOTTEN, MemoryIn, MemoryService, Provenance

pytestmark = pytest.mark.db

KEY_FACT = "Der Ersatzschlüssel für den Keller liegt in der blauen Dose im Flur."


def _vector(text: str) -> list[float]:
    """Deterministic bag-of-words embedding: paraphrases with the same words are close."""
    v = np.zeros(384)
    for word in re.findall(r"\w+", text.lower()):
        v[int(hashlib.sha256(word.encode()).hexdigest(), 16) % 384] += 1.0
    return list(v / (np.linalg.norm(v) or 1.0))


@dataclass
class _Chat:
    text: str


class FakeAI:
    def __init__(self, extracted: list[dict[str, Any]]) -> None:
        self.extracted = extracted

    async def embed(self, texts: list[str], *, kind: str = "document") -> tuple[list[list[float]], str]:
        return [_vector(t) for t in texts], "fake-bow"

    async def chat(self, *a: Any, **kw: Any) -> _Chat:
        return _Chat(json.dumps({"memories": self.extracted, "summary": "Kellerschlüssel besprochen"}))


class FakeBus:
    async def publish(self, event: Any) -> None:
        pass


async def _session_with_transcript(db: Database, text: str) -> str:
    async with db.session() as s:
        session = ConversationSession(trigger="text", mode="pipeline")
        s.add(session)
        await s.flush()
        s.add(TranscriptTurn(session_id=session.id, role="user", text=text))
        s.add(TranscriptTurn(session_id=session.id, role="assistant", text="Ich habe es mir gemerkt."))
        return session.id


async def _cleanup(db: Database, session_ids: list[str]) -> None:
    async with db.session() as s:
        await s.execute(delete(Memory).where(Memory.embedding_model == "fake-bow"))
        await s.execute(delete(ConversationSession).where(ConversationSession.id.in_(session_ids)))


async def test_forgotten_memory_is_not_re_extracted_from_an_older_transcript(db: Database) -> None:
    ai = FakeAI([{"content": KEY_FACT, "kind": "fact", "about": "speaker", "certainty": "stated"}])
    svc = MemoryService(db, ai, FakeBus())  # type: ignore[arg-type]
    sid = await _session_with_transcript(db, f"Merk dir bitte: {KEY_FACT}")
    try:
        hit = await svc.add(MemoryIn(content=KEY_FACT, provenance=Provenance.CONFIRMED))
        assert hit is not None
        await svc.delete(hit.id)  # "Vergiss, wo der Schlüssel liegt"

        # The tombstone keeps no content and is invisible.
        async with db.session() as s:
            row = await s.get(Memory, hit.id)
        assert row is not None and row.status == FORGOTTEN and row.content == ""
        assert await svc.search("Ersatzschlüssel Keller") == []

        # The session ends later; extraction must not bring the fact back (nor a summary).
        assert await svc.extract_from_session(sid) == 0
        async with db.session() as s:
            active = (await s.scalars(select(Memory).where(
                Memory.embedding_model == "fake-bow", Memory.status == "active"))).all()
        assert active == []

        # An explicit request to remember it again lifts the block.
        again = await svc.add(MemoryIn(content=KEY_FACT, provenance=Provenance.CONFIRMED))
        assert again is not None
        assert [h.id for h in await svc.search("Ersatzschlüssel Keller")] == [again.id]
    finally:
        await _cleanup(db, [sid])


async def test_unrelated_facts_are_still_extracted(db: Database) -> None:
    ai = FakeAI([{"content": "Julian trinkt morgens gerne Espresso.", "kind": "preference",
                  "about": "speaker", "certainty": "stated"}])
    svc = MemoryService(db, ai, FakeBus())  # type: ignore[arg-type]
    sid = await _session_with_transcript(db, "Ich trinke morgens gerne Espresso.")
    try:
        forgotten = await svc.add(MemoryIn(content=KEY_FACT))
        assert forgotten is not None
        await svc.delete(forgotten.id)
        assert await svc.extract_from_session(sid) == 1
    finally:
        await _cleanup(db, [sid])
