"""Voice profiles: consent, enrolment, identification with margin, deletion on revocation."""

from __future__ import annotations

import numpy as np
import pytest

from justai.common.errors import ValidationFailed
from justai.db.engine import Database
from justai.identity.service import IdentityService, PersonIn
from justai.identity.voice import VoiceProfiles

pytestmark = pytest.mark.db


def unit(*v: float) -> np.ndarray:
    a = np.zeros(256, np.float32)
    a[: len(v)] = v
    return a / np.linalg.norm(a)


class FakeEmbedder:
    """Voice = first sample value: 1 -> Anna, 2 -> Ben, 3 -> someone between both."""

    def embed(self, pcm: np.ndarray) -> np.ndarray | None:
        return {1: unit(1, 0), 2: unit(0, 1), 3: unit(1, 1)}.get(int(pcm[0]))


class FakeBus:
    async def publish(self, event: object) -> None:
        pass


def speech(voice: int, seconds: float = 6) -> list[np.ndarray]:
    return [np.full(int(seconds * 16000), voice, np.int16)]


async def test_voice_profiles(db: Database) -> None:
    identity = IdentityService(db, FakeBus())  # type: ignore[arg-type]
    voices = VoiceProfiles(db, FakeEmbedder())  # type: ignore[arg-type]
    identity.on_voice_changed = voices.reload
    anna = await identity.create(PersonIn(name="Anna VoiceTest"))
    ben = await identity.create(PersonIn(name="Ben VoiceTest"))
    try:
        with pytest.raises(ValidationFailed, match="Einwilligung"):
            await voices.enroll(anna.id, speech(1), session_id=None)
        await identity.set_consent(anna.id, "voice", True, {"test": True})
        await identity.set_consent(ben.id, "voice", True, {"test": True})
        with pytest.raises(ValidationFailed, match="zu wenig Sprache"):
            await voices.enroll(anna.id, speech(1, seconds=2), session_id=None)
        assert await voices.enroll(anna.id, speech(1), session_id=None) >= 2
        await voices.enroll(ben.id, speech(2), session_id=None)

        assert (await voices.identify(np.full(16000, 1, np.int16))).person_id == anna.id  # type: ignore[union-attr]
        assert (await voices.identify(np.full(16000, 2, np.int16))).person_id == ben.id  # type: ignore[union-attr]
        assert await voices.identify(np.full(16000, 3, np.int16)) is None  # ambiguous: no name

        await identity.set_consent(anna.id, "voice", False, {"test": True})  # revocation deletes
        assert anna.id not in await voices.counts()
        assert await voices.identify(np.full(16000, 1, np.int16)) is None
    finally:
        await identity.delete(anna.id)
        await identity.delete(ben.id)
    assert ben.id not in await voices.counts()
