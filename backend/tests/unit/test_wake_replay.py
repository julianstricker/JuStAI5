"""Speech right after the wakeword: where the replay to the new session starts."""

from __future__ import annotations

import numpy as np

from justai.audio.processor import ProcessedFrame
from justai.conversation.session import WAKE_LOOKBACK_S, replay_start


def frames(vads: list[float], t0: float = 10.0) -> list[ProcessedFrame]:
    pcm = np.zeros(160, np.int16)
    return [ProcessedFrame(t=t0 + i * 0.01, pcm=pcm, vad=v, speech=v >= 0.35, gated=False, echo_window=False)
            for i, v in enumerate(vads)]


def test_no_pause_starts_shortly_before_the_detection() -> None:
    # "Hey Jarvis wie spät ist es": speech goes on through and after the detection at t=11.0
    buf = frames([0.9] * 300)
    assert abs(replay_start(buf, 11.0) - (11.0 - WAKE_LOOKBACK_S)) < 1e-9


def test_pause_starts_after_the_tail_of_the_wake_phrase() -> None:
    # detection at 11.0, 80 ms reverb tail, then silence, question from 12.0
    vads = [0.9] * 100 + [0.8] * 8 + [0.05] * 92 + [0.9] * 100
    start = replay_start(frames(vads), 11.0)
    assert 11.08 - 1e-9 <= start < 11.2
    assert start < 12.0


def test_short_dips_inside_speech_are_no_pause() -> None:
    vads = ([0.9] * 10 + [0.1] * 8) * 20  # 80 ms gaps between syllables
    assert abs(replay_start(frames(vads), 11.0) - (11.0 - WAKE_LOOKBACK_S)) < 1e-9
