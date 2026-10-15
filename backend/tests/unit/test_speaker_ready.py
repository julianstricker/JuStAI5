"""Output to a camera speaker must not start before the backchannel is ready."""

import asyncio

import numpy as np

from justai.audio.io import SpeakerChannel


class SlowSink:
    sample_rate = 16000
    continuous = True
    latency_hint_s = 0.0

    def __init__(self) -> None:
        self.ready = False
        self.frames: list[np.ndarray] = []

    async def open(self) -> None:
        return None

    async def write(self, pcm: np.ndarray) -> None:
        self.frames.append(pcm)

    async def flush(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def test_voiced_audio_waits_for_ready_sink_and_nothing_is_lost() -> None:
    sink = SlowSink()
    speaker = SpeakerChannel("cam", sink)  # type: ignore[arg-type]
    tone = np.full(16000 // 2, 1000, np.int16)  # 0.5 s = 25 frames
    done = speaker.begin("u1")
    await speaker.enqueue("u1", tone)
    speaker.end("u1")
    await asyncio.sleep(0.3)
    assert sink.frames and all(not f.any() for f in sink.frames)  # only silence so far
    assert not done.is_set()
    sink.ready = True
    await asyncio.wait_for(done.wait(), 2)
    voiced = [f for f in sink.frames if f.any()]
    assert len(voiced) == 25
    await speaker.close()


async def test_continuous_sink_stays_open_without_idle_timeout() -> None:
    sink = SlowSink()
    sink.ready = True
    speaker = SpeakerChannel("cam", sink)  # type: ignore[arg-type]
    assert speaker.idle_close_s is None
    await speaker.warm_up()
    await asyncio.sleep(0.2)
    assert speaker._task is not None and not speaker._task.done()
    await speaker.close()
