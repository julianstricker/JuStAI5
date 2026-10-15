"""Audio input and output channels (one per device).

* :class:`MicChannel` produces timestamped 16 kHz PCM from a device and fans it
  out to subscribers (endpoint processors, diagnostics).
* :class:`SpeakerChannel` plays queued assistant audio in real time through a
  sink and reports every emitted frame (with its emission time) to observers -
  this is the reference signal for echo handling.
"""

from __future__ import annotations

import asyncio
import contextlib
import secrets
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from justai_sdk.audio import AudioChunk, Int16Array
from justai_sdk.ports.devices import AudioSink, AudioSource

from justai.audio.dsp import SR, StreamResampler, dbfs
from justai.audio.echo import SampleClock
from justai.logging import get_logger
from justai.media.go2rtc import Go2rtcClient

log = get_logger(__name__)


@dataclass(frozen=True)
class MicChunk:
    t: float  # capture time (monotonic) of the first sample
    pcm: Int16Array  # 16 kHz mono


# ============================================================================ input


class MicSource(Protocol):
    def stream(self) -> AsyncIterator[MicChunk]: ...


class FfmpegMicSource:
    """Pulls the audio track of a go2rtc stream via RTSP and decodes it with ffmpeg."""

    CHUNK_BYTES = 640  # 20 ms @ 16 kHz s16le

    def __init__(self, rtsp_url: str) -> None:
        self.rtsp_url = rtsp_url

    async def stream(self) -> AsyncIterator[MicChunk]:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-fflags", "nobuffer", "-flags", "low_delay", "-probesize", "32",
            "-analyzeduration", "0", "-rtsp_transport", "tcp", "-i", self.rtsp_url,
            "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "pipe:1",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        clock = SampleClock()
        assert proc.stdout is not None and proc.stderr is not None
        try:
            while True:
                data = await asyncio.wait_for(proc.stdout.read(self.CHUNK_BYTES * 5), timeout=10)
                if not data:
                    break
                usable = len(data) - (len(data) % 2)
                pcm = np.frombuffer(data[:usable], dtype="<i2").astype(np.int16)
                yield MicChunk(clock.stamp(pcm.size), pcm)
        finally:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            err = (await proc.stderr.read()).decode(errors="replace")[-300:]
            await proc.wait()
            if err.strip():
                log.warning("ffmpeg mic ended", detail=err.strip())


class DeviceMicSource:
    """Adapter for plugin-provided microphones (SDK ``AudioSource``)."""

    def __init__(self, source: AudioSource) -> None:
        self.source = source

    async def stream(self) -> AsyncIterator[MicChunk]:
        resampler = StreamResampler(self.source.sample_rate, SR)
        clock = SampleClock()
        async for chunk in self.source.stream():
            pcm = resampler.process(chunk.pcm)
            if pcm.size:
                yield MicChunk(clock.stamp(pcm.size), pcm)


MicSubscriber = asyncio.Queue[MicChunk]


class MicChannel:
    def __init__(self, device_id: str, source: MicSource) -> None:
        self.device_id = device_id
        self.source = source
        self._subscribers: dict[str, MicSubscriber] = {}
        self.level_db = -120.0
        self.overruns = 0
        self.chunks = 0
        self.last_chunk_at: float | None = None

    def subscribe(self, name: str, maxsize: int = 200) -> MicSubscriber:
        q: MicSubscriber = asyncio.Queue(maxsize)
        self._subscribers[name] = q
        return q

    def unsubscribe(self, name: str) -> None:
        self._subscribers.pop(name, None)

    async def run(self) -> None:
        """Runs until the source ends (supervisor restarts it)."""
        async for chunk in self.source.stream():
            self.chunks += 1
            self.last_chunk_at = time.monotonic()
            self.level_db = 0.8 * self.level_db + 0.2 * dbfs(chunk.pcm)
            for q in self._subscribers.values():
                if q.full():
                    with contextlib.suppress(asyncio.QueueEmpty):
                        q.get_nowait()
                    self.overruns += 1
                q.put_nowait(chunk)
        raise ConnectionError(f"microphone stream of {self.device_id} ended")


# =========================================================================== output


class OutputSink(Protocol):
    sample_rate: int
    continuous: bool  # needs a continuous stream (silence when idle)
    latency_hint_s: float

    @property
    def ready(self) -> bool:
        """False while the device path is still being set up: voiced audio is held back."""

    async def open(self) -> None: ...

    async def write(self, pcm: Int16Array) -> None: ...

    async def flush(self) -> None: ...

    async def close(self) -> None: ...


class DeviceSinkAdapter:
    """Adapter for plugin-provided speakers (SDK ``AudioSink``)."""

    continuous = False
    ready = True

    def __init__(self, sink: AudioSink, latency_hint_s: float = 0.2) -> None:
        self.sink = sink
        self.sample_rate = SR
        self.latency_hint_s = latency_hint_s
        self._resampler = StreamResampler(SR, sink.sample_rate)

    async def open(self) -> None:
        return None

    async def write(self, pcm: Int16Array) -> None:
        out = self._resampler.process(pcm)
        if out.size:
            await self.sink.write(AudioChunk(out, self.sink.sample_rate))

    async def flush(self) -> None:
        flush = getattr(self.sink, "flush", None)
        if flush:
            await flush()

    async def close(self) -> None:
        return None


@dataclass
class TalkbackStats:
    connections: int = 0
    connected: bool = False
    bytes_pulled: int = 0
    dropped_frames: int = 0
    last_pull: float = 0.0
    first_pull: float = 0.0  # when go2rtc started pulling the current stream


class TalkbackRoutes:
    """Registry of live WAV streams that go2rtc pulls from the core."""

    def __init__(self) -> None:
        self._streams: dict[str, asyncio.Queue[bytes | None]] = {}
        self.stats: dict[str, TalkbackStats] = {}

    def create(self) -> tuple[str, asyncio.Queue[bytes | None]]:
        token = secrets.token_urlsafe(24)
        q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=50)
        self._streams[token] = q
        self.stats[token] = TalkbackStats()
        return token, q

    def get(self, token: str) -> asyncio.Queue[bytes | None] | None:
        return self._streams.get(token)

    def remove(self, token: str) -> None:
        self.stats.pop(token, None)
        q = self._streams.pop(token, None)
        if q is not None:
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(None)


def wav_stream_header(sample_rate: int) -> bytes:
    import struct

    return (b"RIFF" + struct.pack("<I", 0xFFFFFFFF) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16) +
            b"data" + struct.pack("<I", 0xFFFFFFFF))


class Go2rtcTalkbackSink:
    """Plays audio to a camera speaker through the go2rtc backchannel.

    go2rtc pulls an endless, real-time paced WAV stream from the core
    (``/internal/talkback/<token>.wav``) and forwards it to the device.
    """

    continuous = True
    CHECK_INTERVAL_S = 1.0
    DELIVERY_TIMEOUT_S = 6.0

    def __init__(self, go2rtc: Go2rtcClient, stream: str, routes: TalkbackRoutes,
                 core_url: str, latency_hint_s: float = 2.0, settle_s: float = 1.5) -> None:
        self.go2rtc = go2rtc
        # go2rtc first starts ffmpeg, then attaches the camera backchannel: audio sent in
        # this phase is lost (the first test tone after a pause was never audible).
        self.settle_s = settle_s
        self.stream = stream
        self.routes = routes
        self.core_url = core_url.rstrip("/")
        self.sample_rate = SR
        self.latency_hint_s = latency_hint_s
        self._token: str | None = None
        self._queue: asyncio.Queue[bytes | None] | None = None
        self._opened_at = 0.0
        # Delivery check: go2rtc may keep pulling our stream while the route to the camera
        # is gone (after a camera reconnect) - audio would vanish silently.
        self._monitor: asyncio.Task[None] | None = None
        self._delivering = False
        self._restart_requested = False
        self._failed_restarts = 0
        self._next_restart = 0.0

    async def open(self) -> None:
        if self._token is not None:
            return
        self._token, self._queue = self.routes.create()
        self._opened_at = time.monotonic()
        url = f"{self.core_url}/internal/talkback/{self._token}.wav"
        self._delivering = False
        await self.go2rtc.play_live(self.stream, url)
        if self._monitor is None or self._monitor.done():
            self._monitor = asyncio.create_task(self._watch_delivery(), name=f"talkback-watch:{self.stream}")

    async def _watch_delivery(self) -> None:
        last: int | None = None
        last_change = time.monotonic()
        while True:
            await asyncio.sleep(self.CHECK_INTERVAL_S)
            if self._token is None:
                continue
            try:
                sent = await self.go2rtc.backchannel_bytes(self.stream)
            except Exception:
                sent = None
            now = time.monotonic()
            if sent is not None and last is not None and sent > last:
                last_change = now
                if not self._delivering:
                    log.info("talkback delivering to device", stream=self.stream)
                self._delivering = True
                self._failed_restarts = 0
            elif now - max(last_change, self._opened_at) > self.DELIVERY_TIMEOUT_S:
                self._delivering = False
                if now >= self._next_restart and not self._restart_requested:
                    log.warning("talkback not reaching the device, rebuilding the route",
                                stream=self.stream, route=sent is not None)
                    self._restart_requested = True
                    self._failed_restarts += 1
                    self._next_restart = now + min(60.0, self.DELIVERY_TIMEOUT_S * 2 ** self._failed_restarts)
            last = sent

    @property
    def stats(self) -> TalkbackStats | None:
        return self.routes.stats.get(self._token) if self._token else None

    @property
    def ready(self) -> bool:
        st = self.stats
        return bool(st and st.connected and st.first_pull and self._delivering
                    and time.monotonic() - st.first_pull >= self.settle_s)

    async def write(self, pcm: Int16Array) -> None:
        if self._restart_requested:
            self._restart_requested = False
            await self.flush()
        if self._queue is None:
            return
        data = pcm.astype("<i2").tobytes()
        if self._queue.full():  # consumer (go2rtc) is not pulling: drop oldest
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
            st = self.stats
            if st is not None:
                st.dropped_frames += 1
                # go2rtc stopped pulling (e.g. camera reconnected): re-establish the stream.
                if time.monotonic() - max(st.last_pull, self._opened_at) > 3.0:
                    log.warning("talkback stream stalled, reconnecting", stream=self.stream)
                    await self.flush()
                    return
        self._queue.put_nowait(data)

    async def flush(self) -> None:
        """Drop audio buffered in go2rtc/ffmpeg by restarting the talkback stream."""
        await self.close()
        await self.open()

    async def close(self) -> None:
        self._delivering = False
        if self._token is not None:
            self.routes.remove(self._token)
            self._token, self._queue = None, None
            with contextlib.suppress(Exception):
                await self.go2rtc.stop_playback(self.stream)

    async def shutdown(self) -> None:
        """Final close (device removed): also stops the delivery check."""
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
            self._monitor = None
        await self.close()


FrameObserver = Callable[[float, Int16Array, bool], None]


@dataclass
class _Utterance:
    id: str
    done: asyncio.Event
    remaining: int = 0  # queued samples
    finished_enqueue: bool = False


class SpeakerChannel:
    """Real-time paced playout with emission timestamps."""

    FRAME = SR // 50  # 20 ms

    def __init__(self, device_id: str, sink: OutputSink, idle_close_s: float | None = None) -> None:
        self.device_id = device_id
        self.sink = sink
        # None: keep a continuous sink open while the device is online. Re-opening a camera
        # backchannel takes seconds, so closing it made the start of the next output inaudible.
        # Battery devices can set a timeout (device setting speaker_idle_close_s).
        self.idle_close_s = idle_close_s
        self._queue: list[tuple[str, Int16Array]] = []
        self._utterances: dict[str, _Utterance] = {}
        self._observers: dict[str, FrameObserver] = {}
        self._task: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._open = False
        self._opened_at = 0.0
        self._last_voiced = 0.0
        self.emitted_frames = 0
        self.underruns = 0
        self.level_db = -120.0
        self.current_utterance: str | None = None

    # ------------------------------------------------------------------ control
    def add_observer(self, name: str, observer: FrameObserver) -> None:
        self._observers[name] = observer

    def remove_observer(self, name: str) -> None:
        self._observers.pop(name, None)

    @property
    def latency_s(self) -> float:
        return self.sink.latency_hint_s

    @property
    def playing(self) -> bool:
        return bool(self._queue)

    async def warm_up(self) -> None:
        """Open the sink ahead of time (go2rtc pipelines take a moment to start)."""
        await self._ensure_running()

    async def _ensure_running(self) -> None:
        if not self._open:
            await self.sink.open()
            self._open = True
            self._opened_at = time.monotonic()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._pacer(), name=f"speaker:{self.device_id}")

    def begin(self, utterance_id: str) -> asyncio.Event:
        u = _Utterance(utterance_id, asyncio.Event())
        self._utterances[utterance_id] = u
        return u.done

    async def enqueue(self, utterance_id: str, pcm16k: Int16Array) -> None:
        await self._ensure_running()
        u = self._utterances.get(utterance_id)
        if u is None:
            self.begin(utterance_id)
            u = self._utterances[utterance_id]
        for i in range(0, pcm16k.size, self.FRAME):
            frame = pcm16k[i : i + self.FRAME]
            if frame.size < self.FRAME:
                frame = np.concatenate([frame, np.zeros(self.FRAME - frame.size, np.int16)])
            self._queue.append((utterance_id, frame))
            u.remaining += 1
        self._wake.set()

    def end(self, utterance_id: str) -> None:
        u = self._utterances.get(utterance_id)
        if u is None:
            return
        u.finished_enqueue = True
        if u.remaining == 0:
            self._complete(u)

    async def clear(self) -> list[str]:
        """Barge-in: drop queued audio immediately and flush device buffers."""
        dropped = sorted({uid for uid, _ in self._queue})
        self._queue.clear()
        for u in list(self._utterances.values()):
            self._complete(u)
        with contextlib.suppress(Exception):
            await self.sink.flush()
        return dropped

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.clear()
        shutdown = getattr(self.sink, "shutdown", None)
        await (shutdown() if shutdown is not None else self.sink.close())
        self._open = False

    def _complete(self, u: _Utterance) -> None:
        u.done.set()
        self._utterances.pop(u.id, None)

    # ------------------------------------------------------------------- pacing
    async def _pacer(self) -> None:
        frame_s = self.FRAME / SR
        next_t = time.monotonic()
        silence = np.zeros(self.FRAME, dtype=np.int16)
        while True:
            now = time.monotonic()
            if not self._queue and not self.sink.continuous:
                self.current_utterance = None
                self._wake.clear()
                await self._wake.wait()
                next_t = time.monotonic()
                continue
            if not self._queue and self.idle_close_s is not None \
                    and now - max(self._last_voiced, self._opened_at) > self.idle_close_s:
                await self.sink.close()
                self._open = False
                self._task = None
                return
            if now < next_t:
                await asyncio.sleep(next_t - now)
            elif now - next_t > 0.2:  # event loop stalled: do not burst, resync
                self.underruns += 1
                next_t = now
            if self._queue and self.sink.ready:
                uid, frame = self._queue.pop(0)
                voiced = True
                self.current_utterance = uid
            else:
                uid, frame, voiced = "", silence, False
                self.current_utterance = None
            t_emit = time.monotonic()
            try:
                await self.sink.write(frame)
            except Exception as exc:
                log.warning("speaker write failed", device=self.device_id, error=str(exc))
            self.emitted_frames += 1
            if voiced:
                self._last_voiced = t_emit
                self.level_db = dbfs(frame)
                u = self._utterances.get(uid)
                if u is not None:
                    u.remaining -= 1
                    if u.remaining <= 0 and u.finished_enqueue:
                        self._complete(u)
            for observer in list(self._observers.values()):
                observer(t_emit, frame, voiced)
            next_t += frame_s
