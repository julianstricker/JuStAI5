"""Continuing a recent conversation after a new wakeword (same speaker only)."""

import time
from types import SimpleNamespace

import numpy as np

from justai.ai.config import AISettings
from justai.conversation.context import ConversationContext, build_system_prompt
from justai.conversation.manager import ConversationManager, _Recent


class FakeVoice:
    def __init__(self, emb: np.ndarray | None) -> None:
        self.emb = emb

    def embed(self, pcm: np.ndarray) -> np.ndarray | None:
        return self.emb


def manager() -> ConversationManager:
    audio = SimpleNamespace(set_wake_handler=lambda *a: None)
    return ConversationManager(db=None, bus=None, audio=audio, endpoints=None, rooms=None,  # type: ignore[arg-type]
                               router=None, registry=None, executor=None, jobs=None, recall=None)  # type: ignore[arg-type]


CFG = SimpleNamespace(resume_window_s=300, speaker_check=True)
A = np.array([1.0, 0.0], np.float32)
B = np.array([0.0, 1.0], np.float32)
WAKE = np.zeros(16000, np.int16)


def recent(age_s: float = 60, person: str | None = "p1", voice: np.ndarray | None = A) -> _Recent:
    return _Recent("sess-1", time.monotonic() - age_s, [("user", "Wie wird das Wetter?"), ("assistant", "Sonnig.")],
                   person, voice)


async def test_same_speaker_within_window_continues() -> None:
    m = manager()
    m.voice = FakeVoice(A)  # type: ignore[assignment]
    m._recent["ep"] = recent()
    assert await m._resume_candidate("ep", CFG, WAKE, None) is not None


async def test_other_voice_starts_new_conversation() -> None:
    m = manager()
    m.voice = FakeVoice(B)  # type: ignore[assignment]
    m._recent["ep"] = recent()
    assert await m._resume_candidate("ep", CFG, WAKE, None) is None


async def test_camera_seeing_someone_else_starts_new_conversation() -> None:
    m = manager()
    m._recent["ep"] = recent(person="p1")
    assert await m._resume_candidate("ep", CFG, WAKE, "p2") is None
    assert await m._resume_candidate("ep", CFG, WAKE, "p1") is not None


async def test_window_and_switches() -> None:
    m = manager()
    m._recent["ep"] = recent(age_s=400)
    assert await m._resume_candidate("ep", CFG, WAKE, None) is None
    m._recent["ep"] = recent(age_s=60)
    assert await m._resume_candidate("ep", SimpleNamespace(resume_window_s=0, speaker_check=True), WAKE, None) is None
    m.voice = FakeVoice(B)  # type: ignore[assignment]
    no_check = SimpleNamespace(resume_window_s=300, speaker_check=False)
    assert await m._resume_candidate("ep", no_check, WAKE, None) is not None


def test_prompt_contains_previous_turns() -> None:
    ctx = ConversationContext(session_id="s", endpoint_name="ep", room_id="r", room_name="Poolhaus",
                              previous=[("user", "Wie wird das Wetter?"), ("assistant", "Sonnig.")],
                              previous_age_s=150)
    prompt = build_system_prompt(AISettings(), ctx, [])
    assert "continues your conversation from about 2 minute(s) ago" in prompt
    assert "- User: Wie wird das Wetter?" in prompt and "- You: Sonnig." in prompt
