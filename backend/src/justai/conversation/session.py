"""Conversation sessions.

A session belongs to exactly one interaction endpoint (or is text-only). All audio
output goes to the endpoint's speaker as resolved by the Output Router, so answers
always stay in the room where the conversation happens - also after tool calls,
long processing or provider reconnects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np
from justai_sdk.audio import AudioChunk
from justai_sdk.events import Event, EventSource, new_id
from justai_sdk.ports.ai import (
    ChatEventKind,
    ChatMessage,
    RealtimeConfig,
    RealtimeEventKind,
    Role,
    ToolCall,
)
from justai_sdk.tools import InvocationOrigin, ToolContext, ToolResult

from justai import i18n
from justai.ai.config import AISettings, ModelRole
from justai.ai.router import CLOUD_FALLBACK_NOTICES, AIRouter, DataFlags
from justai.audio.dsp import SR
from justai.audio.processor import ProcessedFrame
from justai.common.tasks import spawn
from justai.conversation.context import ConversationContext, build_system_prompt
from justai.conversation.echo_filter import EchoTranscriptFilter
from justai.conversation.state import SessionState, StateMachine
from justai.conversation.text import SentenceSplitter
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.tools.registry import ToolExecutor, ToolRegistry

log = get_logger(__name__)

# Speech right after the wakeword (see ConversationSession._listen). Measured with
# openWakeWord: detection comes 0.04-0.27 s after the end of "Hey Jarvis".
WAKE_LOOKBACK_S = 0.15  # no pause: start this much before the detection (keeps the first word)
PAUSE_FRAMES = 15  # 150 ms below the speech threshold right after the wakeword = a pause
PAUSE_SEARCH_S = 0.8
SPEECH_VAD = 0.35


def replay_start(frames: list[ProcessedFrame], wake_t: float) -> float:
    """Where the user's words after the wakeword begin.

    Paused after the wakeword: at the pause, so the tail/reverb of "Jarvis" stays out (it
    would become an utterance of its own). Went on without a pause: shortly before the
    detection, so the first word of the question is not cut off."""
    run = 0
    for f in frames:
        if f.t < wake_t:
            continue
        if f.t > wake_t + PAUSE_SEARCH_S:
            break
        run = run + 1 if f.vad < SPEECH_VAD else 0
        if run >= PAUSE_FRAMES:
            return f.t - (PAUSE_FRAMES - 1) * 0.01
    return wake_t - WAKE_LOOKBACK_S

MAX_TOOL_ROUNDS = 6
MAX_HISTORY = 30

def _sorry(language: str | None, *, failed: bool = False) -> str:
    return i18n.text("sorry.failed" if failed else "sorry.error", language)


class AudioPort(Protocol):
    """What a session needs from the audio engine (see ``EndpointAudio``)."""

    listener: Callable[[ProcessedFrame], None] | None
    barge_in_handler: Callable[[], Awaitable[None]] | None

    async def warm_up(self) -> None: ...

    def begin(self, utterance_id: str) -> asyncio.Event: ...

    async def push(self, utterance_id: str, chunk: AudioChunk) -> None: ...

    def end(self, utterance_id: str) -> None: ...

    async def stop_output(self) -> None: ...

    def echo_window_end(self) -> float | None: ...

    def frames_since(self, t: float) -> list[ProcessedFrame]: ...


class SessionStore(Protocol):
    async def add_turn(self, session_id: str, role: str, text: str, meta: dict[str, Any]) -> None: ...


@dataclass
class SessionDeps:
    router: AIRouter
    registry: ToolRegistry
    executor: ToolExecutor
    bus: EventBus
    store: SessionStore
    recall: Any  # MemoryRecall
    settings: AISettings


@dataclass
class TranscriptEntry:
    role: str
    text: str
    t: float = field(default_factory=time.time)


class ConversationSession:
    def __init__(self, session_id: str, ctx: ConversationContext, deps: SessionDeps,
                 audio: AudioPort | None, *, permissions: frozenset[str], mode: str,
                 inactivity_timeout_s: float, end_of_utterance_ms: int, max_utterance_s: float,
                 on_end: Callable[[ConversationSession, str], Awaitable[None]]) -> None:
        self.id = session_id
        self.ctx = ctx
        self.deps = deps
        self.audio = audio
        self.permissions = permissions
        self.mode = mode
        self.sm = StateMachine(inactivity_timeout_s)
        self.end_of_utterance_ms = end_of_utterance_ms
        self.max_utterance_s = max_utterance_s
        self._on_end = on_end
        self.echo_filter = EchoTranscriptFilter()
        self.user_turns = 0
        self.transcript: deque[TranscriptEntry] = deque(maxlen=200)
        self.driver: RealtimeDriver | PipelineDriver | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._ending = False
        self.text_listeners: list[Callable[[str, str], Awaitable[None]]] = []
        self._ignore_until = 0.0
        self._wake_t: float | None = None
        # The speaker's voice (wake phrase + user speech, max. 12 s) for "same speaker?"
        # checks when a later wakeword could continue this conversation. Memory only.
        self.voice_audio: list[np.ndarray] = []
        self._voice_samples = 0
        self.resumed_from: str | None = None
        # Called once when enough speech for a voice identification has been collected.
        self.on_voice_ready: Callable[[ConversationSession], Coroutine[Any, Any, None]] | None = None
        self._voice_ready_sent = False
        self.gated_speech_at_start = self._gated_speech_frames()
        self.sm.on_change(self._state_changed)

    def _gated_speech_frames(self) -> int:
        processor = getattr(self.audio, "processor", None)
        return int(getattr(getattr(processor, "stats", None), "gated_speech_frames", 0))

    @property
    def gated_speech_ms(self) -> int:
        """Speech-like audio the echo gate dropped during this conversation (10 ms frames)."""
        return (self._gated_speech_frames() - self.gated_speech_at_start) * 10

    def add_voice(self, pcm: np.ndarray) -> None:
        if self._voice_samples < 12 * SR:
            self.voice_audio.append(pcm)
            self._voice_samples += pcm.size
        if not self._voice_ready_sent and self._voice_samples >= 3 * SR and self.on_voice_ready is not None:
            self._voice_ready_sent = True
            spawn(self.on_voice_ready(self), name=f"voice-id:{self.id}")

    def set_person(self, person_id: str, name: str) -> None:
        """The speaker became known during the conversation (voice, introduction, face)."""
        self.ctx.person_id, self.ctx.person_name = person_id, name
        if isinstance(self.driver, PipelineDriver):
            self.driver.note_person(name)

    def ignore_audio_until(self, t: float) -> None:
        self._ignore_until = max(self._ignore_until, t)

    def replay_after_wake(self, wake_t: float) -> None:
        """When the session is ready, first feed the endpoint's buffered audio since the
        wakeword (what was said right after it, even without a pause), then continue live."""
        self._wake_t = wake_t

    # ------------------------------------------------------------------ properties
    @property
    def state(self) -> SessionState:
        return self.sm.state

    @property
    def endpoint_id(self) -> str | None:
        return getattr(getattr(self.audio, "endpoint", None), "id", None)

    def tool_context(self, call_id: str) -> ToolContext:
        return ToolContext(call_id=call_id, origin=InvocationOrigin.CONVERSATION,
                           session_id=self.id, endpoint_id=self.endpoint_id,
                           room_id=self.ctx.room_id, person_id=self.ctx.person_id,
                           permissions=self.permissions, language=self.ctx.language,
                           correlation_id=self.id)

    # ------------------------------------------------------------------ lifecycle
    async def start(self, initial_instruction: str | None = None) -> None:
        self.sm.transition(SessionState.STARTING, self.ctx.trigger)
        if self.audio is not None:
            self.audio.barge_in_handler = self._on_barge_in
            spawn(self.audio.warm_up())
        memories = await self._recall("")
        system = build_system_prompt(self.deps.settings, self.ctx, memories)
        driver_cls = RealtimeDriver if self.mode == "realtime" else PipelineDriver
        self.driver = driver_cls(self, system)
        await self.driver.start()
        self._watchdog = asyncio.create_task(self._watch(), name=f"session-watch:{self.id}")
        await self.publish("conversation.session.started", {
            "endpoint_id": self.endpoint_id, "trigger": self.ctx.trigger, "mode": self.mode,
            "resumed_from": self.resumed_from, "person_id": self.ctx.person_id})
        if initial_instruction:
            self._listen()
            self.sm.try_transition(SessionState.PROCESSING, "proactive")
            await self.driver.inject(initial_instruction)
        else:
            self.sm.try_transition(SessionState.LISTENING, "ready")
            self._listen()

    def _listen(self) -> None:
        """Attach to the microphone. Buffered audio since the wakeword is replayed first; no await
        between replay and attaching, so no frame is lost or delivered twice."""
        if self.audio is None or self._ending:
            return
        if self._wake_t is not None:
            buffered = self.audio.frames_since(self._wake_t - 1.0)
            start = replay_start(buffered, self._wake_t)
            self.ignore_audio_until(start)
            replay = [f for f in buffered if f.t >= start]
            log.info("replaying speech after the wakeword", session=self.id,
                     paused=start > self._wake_t, seconds=round(len(replay) * 0.01, 2),
                     speech_frames=sum(1 for f in replay if f.speech and not f.gated))
            for frame in replay:
                self._on_frame(frame)
        self.audio.listener = self._on_frame

    async def end(self, reason: str) -> None:
        if self._ending:
            return
        self._ending = True
        if self.audio is not None:
            self.audio.listener = None
            self.audio.barge_in_handler = None
        if self.driver is not None:
            with contextlib.suppress(Exception):
                await self.driver.close()
        if self._watchdog and self._watchdog is not asyncio.current_task():
            self._watchdog.cancel()
        self.sm.try_transition(SessionState.ENDED, reason)
        await self.publish("conversation.session.ended", {"reason": reason,
                                                          "user_turns": self.user_turns})
        await self._on_end(self, reason)

    async def _watch(self) -> None:
        while not self.sm.ended:
            await asyncio.sleep(0.25)
            if self.audio is not None:
                window_end = self.audio.echo_window_end()
                if window_end is not None:
                    self.sm.activity(at=window_end)
            if self.sm.timed_out():
                await self.end("inactivity")
                return

    # ---------------------------------------------------------------------- input
    def _on_frame(self, frame: ProcessedFrame) -> None:
        if frame.t < self._ignore_until:
            return  # tail of the wakeword itself
        if frame.speech and not frame.gated:
            self.sm.activity(frame.t)
            if self.state == SessionState.LISTENING:
                self.add_voice(frame.pcm)
        if self.driver is not None and not frame.gated and self.state in (
                SessionState.LISTENING, SessionState.PROCESSING, SessionState.SPEAKING):
            self.driver.push_frame(frame)

    async def _on_barge_in(self) -> None:
        if self.state != SessionState.SPEAKING:
            return
        await self.publish("conversation.barge_in", {})
        if self.audio is not None:
            await self.audio.stop_output()
        if self.driver is not None:
            await self.driver.interrupt()
        self.sm.try_transition(SessionState.LISTENING, "barge_in")
        self.sm.activity()

    async def send_text(self, text: str) -> None:
        """Typed input (admin chat, display interaction)."""
        if self.driver is not None:
            self.sm.activity()
            await self.driver.user_text(text)

    async def inject(self, instruction: str) -> None:
        if self.driver is not None:
            self.sm.try_transition(SessionState.PROCESSING, "inject")
            await self.driver.inject(instruction)

    # ------------------------------------------------------------- shared helpers
    async def record_user(self, text: str, meta: dict[str, Any] | None = None) -> bool:
        """Store a user utterance. Returns False if it was recognised as echo."""
        text = text.strip()
        if not text:
            return False
        if self.echo_filter.is_echo(text):
            log.info("echo transcript suppressed", session=self.id)
            await self.publish("audio.echo.suppressed", {"similarity": round(
                self.echo_filter.similarity(text), 2), "length": len(text)})
            return False
        self.user_turns += 1
        self.transcript.append(TranscriptEntry("user", text))
        await self.deps.store.add_turn(self.id, "user", text, meta or {})
        await self.publish("conversation.user.utterance", {"text": text})
        return True

    async def record_assistant(self, text: str, meta: dict[str, Any] | None = None) -> None:
        text = text.strip()
        if not text:
            return
        self.echo_filter.assistant_said(text)
        self.transcript.append(TranscriptEntry("assistant", text))
        await self.deps.store.add_turn(self.id, "assistant", text, meta or {})
        await self.publish("conversation.assistant.utterance", {"text": text})
        for listener in self.text_listeners:
            with contextlib.suppress(Exception):
                await listener("assistant", text)

    async def run_tool(self, call: ToolCall) -> ToolResult:
        ctx = self.tool_context(call.id)
        if call.name in ("assistant__confirm_action", "assistant.confirm_action"):
            token = str(call.arguments.get("token", ""))
            result = await self.deps.executor.confirm(token, ctx)
        else:
            result = await self.deps.executor.execute(call.name, call.arguments, ctx)
        await self.deps.store.add_turn(self.id, "tool", result.message or "", {
            "tool": call.name, "ok": result.ok, "error_code": result.error_code})
        return result

    async def _recall(self, query: str) -> list[str]:
        if self.deps.recall is None:
            return []
        try:
            return list(await self.deps.recall.recall(query, person_id=self.ctx.person_id,
                                                      room_id=self.ctx.room_id))
        except Exception as exc:
            log.warning("memory recall failed", error=str(exc))
            return []

    async def publish(self, type: str, payload: dict[str, Any]) -> None:
        await self.deps.bus.publish(Event(
            type=type, payload={"session_id": self.id, **payload}, correlation_id=self.id,
            source=EventSource(kind="session", session_id=self.id, room_id=self.ctx.room_id,
                               endpoint_id=self.endpoint_id)))

    def _state_changed(self, old: SessionState, new: SessionState, reason: str) -> None:
        spawn(self.publish("conversation.state.changed", {
            "from": old.value, "to": new.value, "reason": reason}))

    # ------------------------------------------------------------------- speaking
    async def speak_stream(self, uid: str, chunk: AudioChunk) -> None:
        if self.audio is None:
            return
        if self.state != SessionState.SPEAKING:
            self.sm.try_transition(SessionState.SPEAKING, "audio")
        await self.audio.push(uid, chunk)


def tool_result_payload(result: ToolResult) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": result.ok}
    if result.message:
        payload["message"] = result.message
    if result.data is not None:
        payload["data"] = result.data
    if result.error_code:
        payload["error_code"] = result.error_code
    if result.confirmation_token:
        payload["confirmation_token"] = result.confirmation_token
    text = json.dumps(payload, ensure_ascii=False, default=str)
    if len(text) > 12000:
        payload["data"] = "[truncated]"
    return payload


# ============================================================================ realtime


class RealtimeDriver:
    """Native speech-to-speech (e.g. Gemini Live). Audio is only forwarded while the
    session is active and the frame is not gated by the echo guard."""

    SEND_BATCH = 4  # 4 x 10 ms

    def __init__(self, session: ConversationSession, system_prompt: str) -> None:
        self.s = session
        self.system_prompt = system_prompt
        self.rt: Any = None
        self._queue: asyncio.Queue[np.ndarray] = asyncio.Queue(maxsize=1500)  # room for replayed audio
        self._tasks: list[asyncio.Task[None]] = []
        self._uid: str | None = None
        self._done: asyncio.Event | None = None
        self._user_buf = ""
        self._assistant_buf = ""
        self._closing = False
        self._suppress_output = False
        self._turn_open = False  # the provider is still generating the current answer
        self._generation = 0

    async def start(self) -> None:
        specs = self.s.deps.registry.specs(self.s.permissions)
        settings = self.s.deps.settings
        primary = self.s.ctx.language or settings.default_language
        config = RealtimeConfig(model="", instructions=self.system_prompt, tools=specs,
                                language=primary,
                                languages=[primary, *[x for x in settings.languages if x != primary]],
                                vocabulary=self.s.ctx.vocabulary)
        self.rt, cand = await self.s.deps.router.connect_realtime(config)
        log.info("realtime connected", session=self.s.id, provider=cand.ref.provider,
                 model=cand.ref.model)
        self._tasks = [asyncio.create_task(self._receive(), name=f"rt-recv:{self.s.id}"),
                       asyncio.create_task(self._send(), name=f"rt-send:{self.s.id}")]

    def push_frame(self, frame: ProcessedFrame) -> None:
        if self._queue.full():
            return
        self._queue.put_nowait(frame.pcm)

    async def _send(self) -> None:
        batch: list[np.ndarray] = []
        while True:
            batch.append(await self._queue.get())
            if len(batch) >= self.SEND_BATCH:
                pcm = np.concatenate(batch)
                batch.clear()
                await self.rt.send_audio(AudioChunk(pcm, SR))

    async def _receive(self) -> None:
        s = self.s
        try:
            async for ev in self.rt.events():
                if ev.kind == RealtimeEventKind.AUDIO and ev.audio is not None:
                    await self._flush_user()
                    if self._suppress_output:
                        continue
                    self._turn_open = True
                    if self._uid is None and s.audio is not None:
                        self._uid = new_id("utt")
                        self._done = s.audio.begin(self._uid)
                    if self._uid is not None:
                        await s.speak_stream(self._uid, ev.audio)
                elif ev.kind == RealtimeEventKind.INPUT_TRANSCRIPT:
                    self._user_buf += ev.text
                    s.sm.activity()
                elif ev.kind == RealtimeEventKind.OUTPUT_TRANSCRIPT:
                    self._assistant_buf += ev.text
                elif ev.kind == RealtimeEventKind.TOOL_CALL and ev.tool_call is not None:
                    await self._flush_user()
                    s.sm.try_transition(SessionState.PROCESSING, "tool_call")
                    spawn(self._tool(ev.tool_call))
                elif ev.kind == RealtimeEventKind.INTERRUPTED:
                    if s.audio is not None:
                        await s.audio.stop_output()
                    await self._finish_turn(interrupted=True)
                elif ev.kind == RealtimeEventKind.TURN_COMPLETE:
                    await self._flush_user()
                    await self._finish_turn()
                elif ev.kind == RealtimeEventKind.USAGE and ev.usage:
                    s.deps.router.usage.record(provider="realtime", model="session", role="realtime",
                                               ok=True, input_tokens=ev.usage.input_tokens,
                                               output_tokens=ev.usage.output_tokens)
                elif ev.kind in (RealtimeEventKind.ERROR, RealtimeEventKind.CLOSED):
                    if not self._closing:
                        log.warning("realtime session closed", session=s.id, error=ev.error)
                        spawn(s.end("provider_closed"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("realtime receive failed", session=s.id, error=str(exc), exc_info=True)
            if not self._closing:
                spawn(s.end("provider_error"))

    async def _flush_user(self) -> None:
        text, self._user_buf = self._user_buf.strip(), ""
        if not text:
            return
        accepted = await self.s.record_user(text)
        if not accepted:
            # The model heard our own echo: discard whatever it answers to it.
            self._suppress_output = True
            if self.s.audio is not None:
                await self.s.audio.stop_output()

    async def _finish_turn(self, interrupted: bool = False) -> None:
        s = self.s
        self._turn_open = False
        text, self._assistant_buf = self._assistant_buf, ""
        if text and not self._suppress_output:
            await s.record_assistant(text, {"interrupted": interrupted})
        self._suppress_output = False
        uid, done = self._uid, self._done
        self._uid, self._done = None, None
        self._generation += 1
        generation = self._generation
        if uid is not None and s.audio is not None:
            s.audio.end(uid)
        # Generation is usually faster than playback: wait for the speaker in the
        # background so the receive loop keeps handling events (e.g. interruptions).
        spawn(self._back_to_listening(done, generation, interrupted))

    async def _back_to_listening(self, done: asyncio.Event | None, generation: int,
                                 interrupted: bool) -> None:
        if done is not None and not interrupted:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=120)
        s = self.s
        if s.sm.ended or generation != self._generation or self._turn_open:
            return  # a newer answer started meanwhile
        s.sm.try_transition(SessionState.LISTENING, "turn_complete")
        s.sm.activity()

    async def _tool(self, call: ToolCall) -> None:
        result = await self.s.run_tool(call)
        with contextlib.suppress(Exception):
            await self.rt.send_tool_result(call, tool_result_payload(result))

    async def interrupt(self) -> None:
        if self._turn_open:
            self._suppress_output = True  # drop the rest of the answer being generated

    async def inject(self, text: str) -> None:
        await self.rt.send_text(f"[System event, not spoken by the user] {text}",
                                end_of_turn=True)

    async def user_text(self, text: str) -> None:
        await self.s.record_user(text, {"typed": True})
        await self.rt.send_text(text, end_of_turn=True)

    async def close(self) -> None:
        self._closing = True
        for t in self._tasks:
            t.cancel()
        if self.rt is not None:
            await self.rt.close()


# ============================================================================ pipeline


class PipelineDriver:
    """VAD endpointing -> STT -> LLM (with tools) -> sentence-wise streaming TTS."""

    PRE_ROLL = 30  # frames (300 ms)
    MIN_SPEECH_FRAMES = 20  # shorter "utterances" (clicks, reverb of the wakeword) are dropped

    def __init__(self, session: ConversationSession, system_prompt: str) -> None:
        self.s = session
        self.messages: list[ChatMessage] = [ChatMessage(role=Role.SYSTEM, content=system_prompt)]
        self._pre: deque[np.ndarray] = deque(maxlen=self.PRE_ROLL)
        self._utt: list[np.ndarray] | None = None
        self._silence = 0
        self._speech = 0
        self._turn: asyncio.Task[str] | None = None
        self._lock = asyncio.Lock()  # one turn at a time (voice, text, injected events)

    async def start(self) -> None:
        return None

    # -------------------------------------------------------------- endpointing
    def push_frame(self, frame: ProcessedFrame) -> None:
        if self.s.state not in (SessionState.LISTENING,):
            self._pre.clear()
            self._utt = None
            return
        if self._utt is None:
            self._pre.append(frame.pcm)
            if frame.speech:
                self._utt = list(self._pre)
                self._silence = 0
                self._speech = 0
            return
        self._utt.append(frame.pcm)
        self._silence = 0 if frame.vad >= SPEECH_VAD else self._silence + 1
        self._speech += frame.vad >= SPEECH_VAD
        too_long = len(self._utt) * 10 >= self.s.max_utterance_s * 1000
        if self._silence * 10 >= self.s.end_of_utterance_ms or too_long:
            pcm = np.concatenate(self._utt)
            self._utt = None
            self._pre.clear()
            if self._speech < self.MIN_SPEECH_FRAMES:
                return  # a blip, not words: keep listening instead of blocking for STT
            self.s.sm.try_transition(SessionState.PROCESSING, "utterance")
            self._turn = asyncio.create_task(self._handle_audio(pcm))  # type: ignore[arg-type]

    async def _handle_audio(self, pcm: np.ndarray) -> None:
        s = self.s
        try:
            chunk = AudioChunk(pcm.astype(np.int16), SR)
            prompt = ", ".join(s.ctx.vocabulary) + "." if s.ctx.vocabulary else None
            result = await s.deps.router.transcribe(chunk, language=None, prompt=prompt)
            allowed = s.deps.settings.languages
            if result.language and allowed and result.language not in allowed:
                # Short or unclear utterances get detected as random languages: retry in the
                # session language instead of answering gibberish.
                result = await s.deps.router.transcribe(
                    chunk, language=s.ctx.language or s.deps.settings.default_language, prompt=prompt)
        except Exception as exc:
            log.warning("stt failed", session=s.id, error=str(exc))
            s.sm.try_transition(SessionState.LISTENING, "stt_failed")
            return
        text = result.text.strip()
        if not text or (result.no_speech_probability or 0) > 0.8:
            s.sm.try_transition(SessionState.LISTENING, "no_speech")
            return
        if result.language and result.language in s.deps.settings.languages:
            s.ctx.language = result.language
            self._set_language_hint(result.language)
        if not await s.record_user(text, {"language": result.language}):
            s.sm.try_transition(SessionState.LISTENING, "echo")
            return
        async with self._lock:
            self.messages.append(ChatMessage(role=Role.USER, content=text))
            await self._respond_locked()

    # ------------------------------------------------------------------ respond
    async def _respond(self) -> str:
        async with self._lock:
            return await self._respond_locked()

    async def _respond_locked(self) -> str:
        s = self.s
        specs = s.deps.registry.specs(s.permissions)
        uid = new_id("utt")
        tts_queue: asyncio.Queue[str | None] = asyncio.Queue()
        speaker = asyncio.create_task(self._tts_worker(uid, tts_queue))
        spoken: list[str] = []
        cloud_notices: list[str] = []
        notices_token = CLOUD_FALLBACK_NOTICES.set(cloud_notices)
        announced = False
        try:
            for _round in range(MAX_TOOL_ROUNDS):
                splitter = SentenceSplitter()
                text_parts: list[str] = []
                calls: list[ToolCall] = []
                stream = s.deps.router.stream_chat(ModelRole.CONVERSATION, self._trimmed(),
                                                   tools=specs, flags=DataFlags(personal=True))
                async for ev in stream:
                    if cloud_notices and not announced:
                        announced = True  # say it before the answer that comes from the cloud
                        note = i18n.text("cloud.note", s.ctx.language)
                        spoken.append(note)
                        await tts_queue.put(note)
                    if ev.kind == ChatEventKind.TEXT:
                        text_parts.append(ev.text)
                        for sentence in splitter.push(ev.text):
                            spoken.append(sentence)
                            await tts_queue.put(sentence)
                    elif ev.kind == ChatEventKind.TOOL_CALL and ev.tool_call:
                        calls.append(ev.tool_call)
                for sentence in splitter.flush():
                    spoken.append(sentence)
                    await tts_queue.put(sentence)
                self.messages.append(ChatMessage(role=Role.ASSISTANT, content="".join(text_parts),
                                                 tool_calls=calls))
                if not calls:
                    break
                for call in calls:
                    result = await s.run_tool(call)
                    self.messages.append(ChatMessage(
                        role=Role.TOOL, tool_call_id=call.id, name=call.name,
                        content=json.dumps(tool_result_payload(result), ensure_ascii=False,
                                           default=str)))
            if not "".join(spoken).strip():
                # Tool rounds exhausted or the model ended without text: never stay silent.
                fallback = _sorry(s.ctx.language, failed=True)
                spoken.append(fallback)
                await tts_queue.put(fallback)
        except asyncio.CancelledError:
            speaker.cancel()
            raise
        except Exception as exc:
            log.error("llm turn failed", session=s.id, error=str(exc))
            fallback = _sorry(s.ctx.language)
            spoken.append(fallback)
            await tts_queue.put(fallback)
        finally:
            CLOUD_FALLBACK_NOTICES.reset(notices_token)
            await tts_queue.put(None)
        await speaker
        answer = " ".join(spoken)
        await s.record_assistant(answer)
        if not s.sm.ended:
            s.sm.try_transition(SessionState.LISTENING, "answered")
            s.sm.activity()
        return answer

    async def _tts_worker(self, uid: str, queue: asyncio.Queue[str | None]) -> None:
        s = self.s
        done: asyncio.Event | None = None
        while True:
            sentence = await queue.get()
            if sentence is None:
                break
            if s.audio is None:
                continue
            if done is None:
                done = s.audio.begin(uid)
            try:
                async for chunk in s.deps.router.synthesize(sentence, language=s.ctx.language):
                    await s.speak_stream(uid, chunk)
            except Exception as exc:
                log.warning("tts failed", session=s.id, error=str(exc))
        if done is not None and s.audio is not None:
            s.audio.end(uid)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(done.wait(), timeout=300)

    def _set_language_hint(self, language: str) -> None:
        """Keep one system note with the detected user language (replaced, not appended)."""
        from justai.conversation.context import LANG_NAMES

        name = LANG_NAMES.get(language, language)
        note = ChatMessage(role=Role.SYSTEM, content=f"The user is speaking {name} right now. Answer in {name}.")
        if len(self.messages) > 1 and self.messages[1].role == Role.SYSTEM:
            self.messages[1] = note
        else:
            self.messages.insert(1, note)

    def note_person(self, name: str) -> None:
        system = self.messages[0]
        content = str(system.content or "")
        from justai.conversation.context import UNKNOWN_SPEAKER

        updated = content.replace(UNKNOWN_SPEAKER, f"You are talking to {name}.") if UNKNOWN_SPEAKER in content \
            else content + f"\nYou are talking to {name}."
        self.messages[0] = ChatMessage(role=Role.SYSTEM, content=updated)

    def _trimmed(self) -> list[ChatMessage]:
        if len(self.messages) <= MAX_HISTORY:
            return self.messages
        head = self.messages[:2] if len(self.messages) > 1 and self.messages[1].role == Role.SYSTEM \
            else self.messages[:1]
        tail = self.messages[-MAX_HISTORY:]
        while tail and tail[0].role in (Role.TOOL, Role.SYSTEM):  # no orphaned tool results
            tail = tail[1:]
        return [*head, *tail]

    async def interrupt(self) -> None:
        if self._turn and not self._turn.done():
            self._turn.cancel()

    async def inject(self, text: str) -> None:
        async def run() -> str:
            async with self._lock:
                self.messages.append(ChatMessage(
                    role=Role.USER, content=f"[System event, not spoken by the user] {text}"))
                return await self._respond_locked()

        self._turn = asyncio.create_task(run())

    async def user_text(self, text: str) -> str:
        """Typed input; returns the answer to exactly this message."""
        async with self._lock:
            if not await self.s.record_user(text, {"typed": True}):
                return ""
            self.s.sm.try_transition(SessionState.PROCESSING, "text")
            self.messages.append(ChatMessage(role=Role.USER, content=text))
            return await self._respond_locked()

    async def close(self) -> None:
        if self._turn and not self._turn.done():
            self._turn.cancel()
