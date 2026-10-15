"""Audio engine: wires devices, endpoints, processors, arbitration and output.

* One :class:`MicChannel` / :class:`SpeakerChannel` per device (shared by all
  endpoints that use the device).
* One :class:`EndpointAudio` per enabled interaction endpoint: its processor, the
  echo reference of its own speaker, and playback tracking of *all* speakers in
  the same room (any assistant audio in the room is potential echo).
* Wake candidates go through the :class:`WakeArbiter`; accepted wakes are handed
  to the conversation layer.
* Audio output always goes through the Output Router.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import time
import wave
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import asdict
from typing import Any

import numpy as np
from justai_sdk.audio import AudioChunk, Int16Array
from justai_sdk.events import Event, EventSource
from justai_sdk.ports.devices import Capability
from justai_sdk.ports.wakeword import WakewordProvider

from justai.audio.arbitration import ArbitrationContext, ArbitrationResult, WakeArbiter
from justai.audio.dsp import SR, StreamResampler
from justai.audio.echo import DelayEstimator, PlaybackTracker, ReferenceBuffer
from justai.audio.io import (
    DeviceMicSource,
    DeviceSinkAdapter,
    FfmpegMicSource,
    Go2rtcTalkbackSink,
    MicChannel,
    SpeakerChannel,
    TalkbackRoutes,
)
from justai.audio.processor import EndpointAudioProcessor, ProcessedFrame, WakeCandidate
from justai.common.errors import NotFound, Unavailable
from justai.common.supervisor import Supervisor
from justai.common.tasks import spawn
from justai.devices.manager import DeviceManager, DeviceRuntime
from justai.endpoints.service import DeviceRole, EndpointService, EndpointView
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.media.go2rtc import Go2rtcClient
from justai.output.router import OutputKind, OutputRequest, OutputRouter
from justai.plugins.providers import ProviderRegistry
from justai.system.telemetry import TelemetryHub

log = get_logger(__name__)

FrameListener = Callable[[ProcessedFrame], None]
WakeHandler = Callable[[WakeCandidate, ArbitrationResult], Awaitable[None]]

DEFAULT_NETWORK_LATENCY_S = 2.2  # conservative until calibrated (C200 measured ~1.8 s)
DEFAULT_LOCAL_LATENCY_S = 0.35


def _level_db(pcm: Int16Array) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(pcm.astype(float) ** 2)) / 32768 + 1e-12))


def _envelope_db(pcm: Int16Array, frame: int = 160) -> np.ndarray:
    n = pcm.size // frame
    x = pcm[: n * frame].astype(np.float64).reshape(n, frame)
    return 20 * np.log10(np.sqrt(np.mean(x**2, axis=1)) / 32768 + 1e-9)


def onset_delay(mic: Int16Array, mic_t0: float, ref: Int16Array, ref_t0: float) -> float | None:
    """Delay from playback onsets to microphone onsets.

    Works for devices that duck their microphone during playback (only the first
    ~200 ms of each sound leak into the mic, which defeats correlation methods).
    """
    mic_env, ref_env = _envelope_db(mic), _envelope_db(ref)
    if mic_env.size < 10 or ref_env.size < 10:
        return None

    def onsets(env: np.ndarray, threshold: float) -> list[int]:
        above = env > threshold
        idx = [i for i in range(above.size) if above[i] and (i == 0 or not above[i - 1])]
        merged: list[int] = []
        for i in idx:
            if not merged or i - merged[-1] > 50:  # 0.5 s refractory
                merged.append(i)
        return merged

    # Median = typical background level (ducked periods can be far below it).
    floor = float(np.median(mic_env))
    mic_on = onsets(mic_env, floor + 15)
    ref_on = onsets(ref_env, -45)
    ref_t = [ref_t0 + r * 0.01 for r in ref_on]
    mic_t = [mic_t0 + m * 0.01 for m in mic_on]
    # Consensus: the delay that explains the most playback onsets at once.
    best: list[float] = []
    for r in ref_t:
        for m in mic_t:
            d = m - r
            if not 0.0 <= d <= 4.0:
                continue
            matched = [mm - rr for rr in ref_t for mm in mic_t if abs((mm - rr) - d) <= 0.06]
            if len(matched) > len(best):
                best = matched
    if len(best) < 2:
        return None
    return float(np.median(best))


class EndpointAudio:
    """Audio port of one interaction endpoint (used by conversation sessions)."""

    def __init__(self, engine: AudioEngine, endpoint: EndpointView, processor: EndpointAudioProcessor,
                 reference: ReferenceBuffer, tracker: PlaybackTracker) -> None:
        self.engine = engine
        self.endpoint = endpoint
        self.processor = processor
        self.reference = reference
        self.tracker = tracker
        self.listener: FrameListener | None = None
        self.barge_in_handler: Callable[[], Awaitable[None]] | None = None
        self.mic_device_id: str | None = None
        self._task: asyncio.Task[None] | None = None
        self._resamplers: dict[str, StreamResampler] = {}
        self._active_speaker: SpeakerChannel | None = None

    @property
    def id(self) -> str:
        return self.endpoint.id

    @property
    def room_id(self) -> str:
        return self.endpoint.room_id

    # ------------------------------------------------------------------ input
    def attach_mic(self, channel: MicChannel) -> None:
        self.detach_mic()
        self.mic_device_id = channel.device_id
        queue = channel.subscribe(f"endpoint:{self.id}")

        async def consume() -> None:
            while True:
                chunk = await queue.get()
                out = await self.processor.feed(chunk.t, chunk.pcm)
                if out.barge_in and self.barge_in_handler is not None:
                    await self.barge_in_handler()
                if self.listener is not None:
                    for frame in out.frames:
                        self.listener(frame)
                for wake in out.wakes:
                    await self.engine.submit_wake(wake)

        self._task = asyncio.create_task(consume(), name=f"endpoint-audio:{self.id}")

    def detach_mic(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self.mic_device_id:
            channel = self.engine.mics.get(self.mic_device_id)
            if channel:
                channel.unsubscribe(f"endpoint:{self.id}")
        self.mic_device_id = None

    @property
    def has_input(self) -> bool:
        return self._task is not None

    # ----------------------------------------------------------------- output
    def speaker(self, permissions: frozenset[str] = frozenset()) -> SpeakerChannel:
        decision = self.engine.router.route(OutputRequest(
            OutputKind.AUDIO, origin_endpoint_id=self.id, permissions=permissions))
        channel = self.engine.speakers.get(decision.device_id)
        if channel is None:
            raise Unavailable(f"speaker {decision.device_id} has no audio channel")
        return channel

    async def warm_up(self) -> None:
        with contextlib.suppress(Exception):
            await self.speaker().warm_up()

    def begin(self, utterance_id: str) -> asyncio.Event:
        speaker = self.speaker()
        self._active_speaker = speaker
        return speaker.begin(utterance_id)

    async def push(self, utterance_id: str, chunk: AudioChunk) -> None:
        speaker = self._active_speaker or self.speaker()
        resampler = self._resamplers.get(utterance_id)
        if resampler is None or resampler.in_rate != chunk.sample_rate:
            resampler = self._resamplers[utterance_id] = StreamResampler(chunk.sample_rate, SR)
        pcm = resampler.process(chunk.pcm)
        if pcm.size:
            await speaker.enqueue(utterance_id, pcm)

    def end(self, utterance_id: str) -> None:
        resampler = self._resamplers.pop(utterance_id, None)
        speaker = self._active_speaker
        if speaker is None:
            return
        if resampler is not None:
            tail = resampler.process(np.zeros(0, np.int16), last=True)
            if tail.size:
                spawn(speaker.enqueue(utterance_id, tail))
        speaker.end(utterance_id)

    async def play(self, utterance_id: str, chunks: AsyncIterator[AudioChunk]) -> None:
        done = self.begin(utterance_id)
        async for chunk in chunks:
            await self.push(utterance_id, chunk)
        self.end(utterance_id)
        await done.wait()

    async def stop_output(self) -> None:
        if self._active_speaker is not None:
            await self._active_speaker.clear()
        self.tracker.cancel(time.monotonic())

    def playing(self) -> bool:
        return bool(self._active_speaker and self._active_speaker.playing)

    def echo_window_end(self) -> float | None:
        return self.tracker.echo_window_end(self.processor.latency_s, self.processor.tail_s)

    def stats(self) -> dict[str, Any]:
        st = asdict(self.processor.stats)
        st.update(latency_s=round(self.processor.latency_s, 3), mic=self.mic_device_id,
                  duplex=self.processor.duplex.value)
        return st


class AudioEngine:
    def __init__(self, devices: DeviceManager, endpoints: EndpointService, router: OutputRouter,
                 providers: ProviderRegistry, go2rtc: Go2rtcClient, talkback: TalkbackRoutes,
                 bus: EventBus, telemetry: TelemetryHub, supervisor: Supervisor, *,
                 core_url: str) -> None:
        self.devices = devices
        self.endpoint_service = endpoints
        self.router = router
        self.providers = providers
        self.go2rtc = go2rtc
        self.talkback = talkback
        self.bus = bus
        self.telemetry = telemetry
        self.supervisor = supervisor
        self.core_url = core_url
        self.mics: dict[str, MicChannel] = {}
        self.speakers: dict[str, SpeakerChannel] = {}
        self.endpoints: dict[str, EndpointAudio] = {}
        self.arbiter = WakeArbiter(self._arbitration_context, self._on_arbitrated)
        self._wake_handler: WakeHandler | None = None
        self._has_session: Callable[[str], bool] = lambda _ep: False
        self._telemetry_task: asyncio.Task[None] | None = None
        devices.on_ready_change(self._on_device)

    # --------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        await self.reload_endpoints()
        self._telemetry_task = asyncio.create_task(self._telemetry_loop(), name="audio-telemetry")

    async def stop(self) -> None:
        if self._telemetry_task:
            self._telemetry_task.cancel()
        for ep in list(self.endpoints.values()):
            ep.detach_mic()
            ep.processor.close()
        for device_id in list(self.mics):
            await self.supervisor.stop(f"mic:{device_id}")
        for sp in self.speakers.values():
            await sp.close()

    def set_wake_handler(self, handler: WakeHandler, has_session: Callable[[str], bool]) -> None:
        self._wake_handler = handler
        self._has_session = has_session

    # ------------------------------------------------------------ device hooks
    async def _on_device(self, runtime: DeviceRuntime, ready: bool) -> None:
        device_id = runtime.device_id
        if not ready:
            await self.supervisor.stop(f"mic:{device_id}")
            self.mics.pop(device_id, None)
            speaker = self.speakers.pop(device_id, None)
            if speaker:
                await speaker.close()
            for ep in self.endpoints.values():
                if ep.mic_device_id == device_id:
                    ep.detach_mic()
            return
        handle = runtime.handle
        if handle is None:
            return
        caps = runtime.capabilities
        media = handle.media()
        if Capability.AUDIO_INPUT in caps:
            custom = handle.audio_source()
            if custom is not None:
                source: Any = DeviceMicSource(custom)
            elif runtime.stream:
                source = FfmpegMicSource(self.go2rtc.rtsp(runtime.stream, audio_only=True))
            else:
                source = None
            if source is not None:
                channel = MicChannel(device_id, source)
                self.mics[device_id] = channel
                self.supervisor.start(f"mic:{device_id}", channel.run, max_backoff_s=30)
        if Capability.AUDIO_OUTPUT in caps:
            custom_sink = handle.audio_sink()
            latency = float(str(runtime.settings.get("output_latency_s", 0) or 0))
            if custom_sink is not None:
                sink: Any = DeviceSinkAdapter(custom_sink, latency or DEFAULT_LOCAL_LATENCY_S)
            elif media is not None and media.backchannel and runtime.stream:
                sink = Go2rtcTalkbackSink(self.go2rtc, runtime.stream, self.talkback, self.core_url,
                                          latency or DEFAULT_NETWORK_LATENCY_S)
            else:
                sink = None
            if sink is not None:
                self.speakers[device_id] = SpeakerChannel(device_id, sink)
        await self._rewire()

    # --------------------------------------------------------------- endpoints
    async def reload_endpoints(self) -> None:
        views = {e.id: e for e in await self.endpoint_service.list() if e.enabled}
        for ep_id in list(self.endpoints):
            if ep_id not in views or views[ep_id] != self.endpoints[ep_id].endpoint:
                ep = self.endpoints.pop(ep_id)
                ep.detach_mic()
                ep.processor.close()
        for ep_id, view in views.items():
            if ep_id not in self.endpoints:
                self.endpoints[ep_id] = self._build_endpoint(view)
        await self._rewire()

    def _wakeword_provider(self) -> WakewordProvider | None:
        provider = self.providers.get("wakeword", "openwakeword")
        if provider is None:
            entries = self.providers.all("wakeword")
            provider = entries[0] if entries else None
        return provider  # type: ignore[no-any-return]

    def _build_endpoint(self, view: EndpointView) -> EndpointAudio:
        provider = self._wakeword_provider()
        detector = None
        if provider is not None and view.config.wakeword.enabled:
            try:
                detector = provider.create_detector(view.config.wakeword.models)
            except Exception as exc:
                log.error("wakeword detector unavailable", endpoint=view.id, error=str(exc))
        mic_id = view.primary(DeviceRole.MIC)
        mic_rt = self.devices.get(mic_id) if mic_id else None
        full_duplex = bool(mic_rt and Capability.AUDIO_FULL_DUPLEX in mic_rt.capabilities)
        reference, tracker = ReferenceBuffer(), PlaybackTracker()
        processor = EndpointAudioProcessor(
            view.id, view.config.audio, view.config.wakeword, detector, reference=reference,
            tracker=tracker,
            # Conservative until a speaker channel is attached (see _rewire) or calibrated.
            output_latency_s=DEFAULT_NETWORK_LATENCY_S,
            full_duplex_capable=full_duplex)
        return EndpointAudio(self, view, processor, reference, tracker)

    async def _rewire(self) -> None:
        """Attach endpoint processors to mic channels and speaker observers."""
        audible: dict[str, list[float]] = {ep_id: [] for ep_id in self.endpoints}
        for sp_id, speaker in self.speakers.items():
            for name in [n for n in list(speaker._observers) if n.startswith("ep:")]:
                speaker.remove_observer(name)
            sp_rt = self.devices.get(sp_id)
            sp_room = sp_rt.room_id if sp_rt else None
            for ep in self.endpoints.values():
                own = ep.endpoint.primary(DeviceRole.SPEAKER) == sp_id
                if not own and sp_room != ep.room_id:
                    continue
                speaker.add_observer(f"ep:{ep.id}", self._observer(ep, own))
                audible[ep.id].append(speaker.latency_s)
        for ep in self.endpoints.values():
            # The echo gate uses the latency of the slowest speaker audible at this endpoint.
            if audible[ep.id]:
                ep.processor.output_latency_s = max(audible[ep.id])
            mic_id = ep.endpoint.primary(DeviceRole.MIC)
            channel = self.mics.get(mic_id) if mic_id else None
            if channel is None:
                ep.detach_mic()
            elif ep.mic_device_id != mic_id or not ep.has_input:
                ep.attach_mic(channel)

    @staticmethod
    def _observer(ep: EndpointAudio, own: bool) -> Callable[[float, Int16Array, bool], None]:
        def observe(t: float, frame: Int16Array, voiced: bool) -> None:
            if own:
                ep.reference.add(t, frame)
            ep.tracker.note(t, frame.size / SR, voiced)
        return observe

    def get(self, endpoint_id: str) -> EndpointAudio:
        ep = self.endpoints.get(endpoint_id)
        if ep is None:
            raise NotFound(f"endpoint {endpoint_id} has no active audio")
        return ep

    # ------------------------------------------------------------- arbitration
    async def submit_wake(self, candidate: WakeCandidate) -> None:
        await self.bus.publish(Event(
            type="audio.wakeword.detected",
            source=EventSource(kind="device", endpoint_id=candidate.endpoint_id,
                               room_id=self.endpoints[candidate.endpoint_id].room_id
                               if candidate.endpoint_id in self.endpoints else None),
            payload={"endpoint_id": candidate.endpoint_id, "model": candidate.model,
                     "score": round(candidate.score, 3)},
        ))
        self.arbiter.submit(candidate)

    def _arbitration_context(self, endpoint_id: str) -> ArbitrationContext | None:
        ep = self.endpoints.get(endpoint_id)
        if ep is None:
            return None
        return ArbitrationContext(ep.endpoint.arbitration_group, ep.endpoint.priority,
                                  self._has_session(endpoint_id))

    async def _on_arbitrated(self, result: ArbitrationResult) -> None:
        win = result.winner
        await self.bus.publish(Event(
            type="audio.wakeword.accepted",
            source=EventSource(kind="device", endpoint_id=win.endpoint_id,
                               room_id=self.endpoints[win.endpoint_id].room_id),
            payload={"endpoint_id": win.endpoint_id, "model": win.model, "score": round(win.score, 3),
                     "scores": result.scores},
        ))
        for loser in result.losers:
            await self.bus.publish(Event(type="audio.wakeword.rejected", payload={
                "endpoint_id": loser.endpoint_id, "reason": "arbitration", "winner": win.endpoint_id}))
        if self._wake_handler is not None:
            await self._wake_handler(win, result)

    # ------------------------------------------------------------- diagnostics
    async def _telemetry_loop(self) -> None:
        while True:
            await asyncio.sleep(0.2)
            for ep in self.endpoints.values():
                self.telemetry.publish(f"audio.endpoint.{ep.id}", ep.stats())
            for mic in self.mics.values():
                self.telemetry.publish(f"audio.mic.{mic.device_id}", {
                    "level_db": round(mic.level_db, 1), "chunks": mic.chunks,
                    "overruns": mic.overruns,
                    "stale_s": round(time.monotonic() - mic.last_chunk_at, 2) if mic.last_chunk_at else None})
            for sp in self.speakers.values():
                data: dict[str, Any] = {
                    "playing": sp.playing, "frames": sp.emitted_frames, "underruns": sp.underruns,
                    "latency_s": sp.latency_s, "utterance": sp.current_utterance}
                tb = getattr(sp.sink, "stats", None)
                if tb is not None:
                    data["talkback"] = vars(tb)
                self.telemetry.publish(f"audio.speaker.{sp.device_id}", data)

    async def play_test_tone(self, device_id: str, seconds: float = 1.5, freq: float = 660.0) -> None:
        speaker = self.speakers.get(device_id)
        if speaker is None:
            raise NotFound("device has no audio output channel")
        t = np.arange(int(seconds * SR)) / SR
        env = np.minimum(1, np.minimum(t, seconds - t) * 20)
        tone = (np.sin(2 * np.pi * freq * t) * env * 0.4 * 32767).astype(np.int16)
        uid = f"test-{time.monotonic()}"
        done = speaker.begin(uid)
        await speaker.enqueue(uid, tone)
        speaker.end(uid)
        await asyncio.wait_for(done.wait(), timeout=seconds + 10)

    async def calibrate(self, endpoint_id: str) -> dict[str, Any]:
        """Play chirps through the endpoint speaker and measure the echo delay."""
        ep = self.get(endpoint_id)
        mic = self.mics.get(ep.mic_device_id or "")
        if mic is None:
            raise Unavailable("endpoint has no active microphone")
        speaker = ep.speaker()
        await speaker.warm_up()
        await asyncio.sleep(2.0)  # let a network talkback pipeline settle
        q = mic.subscribe("calibration", maxsize=2000)
        recorded: list[tuple[float, Int16Array]] = []
        t = np.arange(int(0.6 * SR)) / SR
        from scipy.signal import chirp

        sweep = (chirp(t, 400, t[-1], 3200) * 0.5 * 32767).astype(np.int16)
        signal = np.concatenate([np.concatenate([sweep, np.zeros(int(0.9 * SR), np.int16)])
                                 for _ in range(3)])
        try:
            uid = f"calib-{time.monotonic()}"
            done = speaker.begin(uid)
            await speaker.enqueue(uid, signal)
            speaker.end(uid)
            end = time.monotonic() + signal.size / SR + 4.0
            while time.monotonic() < end:
                with contextlib.suppress(TimeoutError):
                    chunk = await asyncio.wait_for(q.get(), timeout=0.5)
                    recorded.append((chunk.t, chunk.pcm))
            await done.wait()
        finally:
            mic.unsubscribe("calibration")
        if not recorded:
            raise Unavailable("no microphone audio during calibration")
        t0 = recorded[0][0]
        pcm = np.concatenate([p for _, p in recorded])
        estimator = DelayEstimator(max_delay_s=4.0, window_s=pcm.size / SR, min_confidence=10.0)
        est = estimator.estimate(pcm, t0, ep.reference)
        last = estimator.last
        onset = onset_delay(pcm, t0, ep.reference.get(t0 - 4.0, pcm.size + 4 * SR), t0 - 4.0)
        delay = est.delay_s if est else onset
        mic_level = _level_db(pcm)
        result: dict[str, Any] = {"delay_s": round(delay, 3) if delay is not None else None,
                  "method": "gcc-phat" if est else ("onset" if onset is not None else None),
                  "gcc_confidence": round(last.confidence, 1) if last else 0.0,
                  "onset_delay_s": round(onset, 3) if onset is not None else None,
                  "mic_level_db": round(mic_level, 1)}
        noise_floor = ep.processor.stats.noise_floor_db
        if delay is not None:
            ep.processor.seed_delay(delay)
            result["interpretation"] = "echo delay measured"
        elif mic_level < noise_floor + 6:
            result["interpretation"] = (
                "no echo reached the microphone: the device most likely mutes its microphone "
                "while its speaker plays (hardware half duplex). This is safe; the conservative "
                f"default latency of {ep.processor.latency_s:.1f} s stays active.")
        else:
            result["interpretation"] = "echo audible but delay not measurable; keep half duplex"
        return result

    async def record_diagnostics(self, endpoint_id: str, seconds: float) -> bytes:
        """Explicitly requested diagnostic recording (processed audio), returned as WAV."""
        ep = self.get(endpoint_id)
        frames: list[Int16Array] = []
        previous = ep.listener

        def tap(frame: ProcessedFrame) -> None:
            frames.append(frame.pcm)
            if previous:
                previous(frame)

        ep.listener = tap
        try:
            await asyncio.sleep(min(seconds, 30))
        finally:
            ep.listener = previous
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(np.concatenate(frames).astype("<i2").tobytes() if frames else b"")
        return buf.getvalue()
