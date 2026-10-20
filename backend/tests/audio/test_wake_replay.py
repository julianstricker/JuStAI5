"""Real openWakeWord + Piper: speech after the wakeword is kept, with and without a pause."""

from __future__ import annotations

import numpy as np
import pytest

from justai.audio.dsp import SR
from justai.audio.echo import PlaybackTracker, ReferenceBuffer
from justai.audio.processor import EndpointAudioProcessor, ProcessedFrame, WakeCandidate
from justai.conversation.session import replay_start
from justai.endpoints.service import AudioConfig, WakewordConfig

from .conftest import speak

pytestmark = pytest.mark.models
VOICE = "en_US-lessac-medium"
T0 = 100.0


async def feed(oww_provider, pcm: np.ndarray) -> tuple[list[ProcessedFrame], list[WakeCandidate]]:  # type: ignore[no-untyped-def]
    proc = EndpointAudioProcessor(
        "ep", AudioConfig(), WakewordConfig(models=["hey_jarvis"], threshold=0.5),
        oww_provider.create_detector(["hey_jarvis"]), reference=ReferenceBuffer(keep_s=20),
        tracker=PlaybackTracker(), output_latency_s=0.5, full_duplex_capable=False)
    frames: list[ProcessedFrame] = []
    wakes: list[WakeCandidate] = []
    for i in range(0, pcm.size - 320, 320):
        out = await proc.feed(T0 + i / SR, pcm[i:i + 320])
        frames += out.frames
        wakes += out.wakes
    proc.close()
    return frames, wakes


def speech_end(pcm: np.ndarray) -> float:
    env = np.abs(pcm[: pcm.size - pcm.size % 160].astype(np.float32)).reshape(-1, 160).max(1)
    return float((np.where(env > 0.01 * 32768)[0][-1] + 1) * 0.01)


async def test_question_without_pause_is_replayed_from_its_first_word(oww_provider) -> None:  # type: ignore[no-untyped-def]
    lead = np.zeros(SR, np.int16)
    wake_end = 1.0 + speech_end(speak("Hey Jarvis", VOICE))
    frames, wakes = await feed(oww_provider, np.concatenate(
        [lead, speak("Hey Jarvis, what is the capital of France?", VOICE), np.zeros(SR, np.int16)]))
    assert wakes, "wakeword not detected"
    start = replay_start(frames, wakes[0].t) - T0
    assert start <= wake_end + 0.05, f"replay starts {start - wake_end:.2f}s after the wake phrase"


async def test_after_a_pause_the_tail_of_the_wake_phrase_is_left_out(oww_provider) -> None:  # type: ignore[no-untyped-def]
    lead = np.zeros(SR, np.int16)
    wake = speak("Hey Jarvis!", VOICE)
    question_at = 1.0 + wake.size / SR + 1.0
    frames, wakes = await feed(oww_provider, np.concatenate(
        [lead, wake, np.zeros(SR, np.int16), speak("What time is it?", VOICE), np.zeros(SR, np.int16)]))
    assert wakes, "wakeword not detected"
    start = replay_start(frames, wakes[0].t)
    assert start > wakes[0].t, "no pause found"
    replayed = [f for f in frames if start <= f.t < T0 + question_at]
    assert sum(f.vad >= 0.35 for f in replayed) < 5, "tail of the wake phrase would be replayed"
