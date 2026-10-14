"""The assistant must never react to its own speech (requirement 8.2, criterion 4).

The assistant deliberately says the wakeword ("Hey Jarvis") in its answer. Its audio
reaches the microphone through a simulated room (network delay, reverb, noise,
optionally Tapo-like hardware ducking). The processor must neither produce a wake
candidate nor let echo frames through as user input - while a real user saying
the wakeword afterwards is still detected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pytest

from justai.audio.dsp import SR
from justai.audio.echo import PlaybackTracker, ReferenceBuffer
from justai.audio.processor import EndpointAudioProcessor, WakeCandidate
from justai.audio.simulation import AcousticParams, AcousticRoom
from justai.endpoints.service import AudioConfig, DuplexMode, WakewordConfig

from .conftest import speak

pytestmark = pytest.mark.models

ASSISTANT_TEXT = "Hey Jarvis! Das hast du mich gefragt. Hey Jarvis, es ist jetzt zehn Uhr."
USER_WAKE = "Hey Jarvis"


@dataclass
class Run:
    wakes: list[WakeCandidate] = field(default_factory=list)
    leaked_speech_frames: int = 0  # echo-only frames that were NOT gated and looked like speech
    gated_frames: int = 0
    barge_ins: list[float] = field(default_factory=list)
    open_speech_after: int = 0


async def simulate(oww_provider, params: AcousticParams, audio: AudioConfig, *,  # type: ignore[no-untyped-def]
                   assume_latency_s: float, user_at: float | None = None,
                   user_text: str = USER_WAKE, user_gain: float = 1.0,
                   barge_in_at: float | None = None, duration_s: float = 14.0,
                   full_duplex_capable: bool = False) -> Run:
    room = AcousticRoom(params)
    reference = ReferenceBuffer(keep_s=20)
    tracker = PlaybackTracker()
    proc = EndpointAudioProcessor(
        "ep", audio, WakewordConfig(models=["hey_jarvis"], threshold=0.5),
        oww_provider.create_detector(["hey_jarvis"]), reference=reference, tracker=tracker,
        output_latency_s=assume_latency_s, full_duplex_capable=full_duplex_capable,
    )
    assistant = speak(ASSISTANT_TEXT)
    t0 = 100.0
    speak_start = t0 + 1.0
    echo_end = speak_start + assistant.size / SR + params.echo_delay_s + 0.3
    if user_at is not None:
        room.user_says(t0 + user_at, speak(user_text, "en_US-lessac-medium"), gain=user_gain)
    if barge_in_at is not None:
        room.user_says(t0 + barge_in_at, speak("Stop, I meant today, not tomorrow please.",
                                               "en_US-lessac-medium"), gain=user_gain)
    run = Run()
    step = 320  # 20 ms
    for i in range(int(duration_s * SR / step)):
        t = t0 + i * step / SR
        k = int(round((t - speak_start) * SR))
        if 0 <= k < assistant.size:
            frame = assistant[k:k + step]
            if frame.size < step:
                frame = np.concatenate([frame, np.zeros(step - frame.size, np.int16)])
            room.speaker_emit(t, frame)
            reference.add(t, frame)
            tracker.note(t, step / SR, voiced=True)
        out = await proc.feed(t, room.mic(t, step))
        run.wakes += out.wakes
        if out.barge_in:
            run.barge_ins.append(t - t0)
            tracker.cancel(t)
        for f in out.frames:
            user_active = user_at is not None and t0 + user_at <= f.t <= t0 + user_at + 1.5
            barging = barge_in_at is not None and f.t >= t0 + barge_in_at
            if f.gated:
                run.gated_frames += 1
            elif speak_start <= f.t <= echo_end and f.vad > 0.5 and not user_active and not barging:
                run.leaked_speech_frames += 1
    proc.close()
    return run


async def test_half_duplex_tapo_like_camera(oww_provider) -> None:  # type: ignore[no-untyped-def]
    """C200-like: 1.8 s network delay, hardware ducking with a 200 ms leak."""
    params = AcousticParams(echo_delay_s=1.8, echo_gain=0.6, hardware_ducking=True)
    run = await simulate(oww_provider, params, AudioConfig(duplex=DuplexMode.HALF),
                         assume_latency_s=2.0, user_at=11.5)
    assert run.leaked_speech_frames == 0
    assert [w.endpoint_id for w in run.wakes] == ["ep"], "only the real user must wake it"
    assert run.wakes[0].t - 100.0 > 11.0


async def test_half_duplex_loud_echo_without_ducking(oww_provider) -> None:  # type: ignore[no-untyped-def]
    params = AcousticParams(echo_delay_s=0.8, echo_gain=0.8)
    run = await simulate(oww_provider, params, AudioConfig(duplex=DuplexMode.HALF),
                         assume_latency_s=1.0, user_at=11.5)
    assert run.leaked_speech_frames == 0
    assert len(run.wakes) == 1 and run.wakes[0].t - 100.0 > 11.0


async def test_underestimated_latency_is_corrected_by_measurement(oww_provider) -> None:  # type: ignore[no-untyped-def]
    """Configured latency is far too small (0.3 s vs. 1.6 s real). The GCC-PHAT
    estimator measures the real delay during playback and extends the gate."""
    params = AcousticParams(echo_delay_s=1.6, echo_gain=0.7)
    run = await simulate(oww_provider, params, AudioConfig(duplex=DuplexMode.HALF),
                         assume_latency_s=0.3, user_at=12.0)
    assert not [w for w in run.wakes if w.t - 100.0 < 11.0], "self-wake from echo"
    assert run.leaked_speech_frames <= 5  # at most the first ~50 ms before measurement


async def test_full_duplex_aec_suppresses_self_wake_and_allows_barge_in(oww_provider) -> None:  # type: ignore[no-untyped-def]
    params = AcousticParams(echo_delay_s=1.2, echo_gain=0.5)
    audio = AudioConfig(duplex=DuplexMode.FULL, barge_in=True)
    run = await simulate(oww_provider, params, audio, assume_latency_s=1.3,
                         barge_in_at=4.0, user_gain=1.6, full_duplex_capable=True)
    assert not run.wakes, "assistant woke itself despite AEC"
    assert run.barge_ins, "user barge-in was not detected"
    assert 4.0 <= run.barge_ins[0] <= 5.5


async def test_full_duplex_echo_alone_never_counts_as_barge_in(oww_provider) -> None:  # type: ignore[no-untyped-def]
    for delay, gain in ((0.3, 0.9), (1.5, 0.6)):
        params = AcousticParams(echo_delay_s=delay, echo_gain=gain, seed=int(delay * 10))
        run = await simulate(oww_provider, params, AudioConfig(duplex=DuplexMode.FULL),
                             assume_latency_s=delay + 0.1, full_duplex_capable=True)
        assert not run.barge_ins, f"echo misread as barge-in (delay {delay})"
        assert not run.wakes
        assert run.leaked_speech_frames == 0
