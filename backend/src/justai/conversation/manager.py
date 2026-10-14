"""Conversation manager: at most one session per interaction endpoint.

Sessions are started by an accepted wakeword, by an authorised automation
(proactive conversation without wakeword) or by typed text. A per-endpoint lock
prevents duplicate activations when a wakeword and an event arrive together.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from justai_sdk.events import new_id
from sqlalchemy import select

from justai.ai.config import ConversationMode as GlobalMode
from justai.ai.router import AIRouter
from justai.audio.arbitration import ArbitrationResult
from justai.audio.engine import AudioEngine
from justai.audio.processor import WakeCandidate
from justai.auth.rbac import conversation_permissions
from justai.common.errors import NotFound, Unavailable
from justai.conversation.context import ConversationContext
from justai.conversation.session import ConversationSession, SessionDeps
from justai.db.engine import Database
from justai.db.models import ConversationSession as SessionRow, Person, TranscriptTurn, User
from justai.endpoints.service import ConversationMode, DeviceRole, EndpointService
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.rooms.service import RoomService
from justai.system.jobs import JobQueue
from justai.tools.registry import ToolExecutor, ToolRegistry

log = get_logger(__name__)


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(self, session_id: str, *, endpoint_id: str | None, room_id: str | None,
                     person_id: str | None, trigger: str, mode: str, language: str | None) -> None:
        async with self.db.session() as s:
            s.add(SessionRow(id=session_id, endpoint_id=endpoint_id, room_id=room_id,
                             person_id=person_id, trigger=trigger, mode=mode, language=language))

    async def add_turn(self, session_id: str, role: str, text: str, meta: dict[str, Any]) -> None:
        async with self.db.session() as s:
            s.add(TranscriptTurn(session_id=session_id, role=role, text=text, meta=meta))

    async def finish(self, session_id: str, reason: str, *, person_id: str | None,
                     language: str | None) -> None:
        async with self.db.session() as s:
            row = await s.get(SessionRow, session_id)
            if row is None:
                return
            row.ended_at = datetime.now(UTC)
            row.end_reason = reason
            row.person_id = person_id or row.person_id
            row.language = language or row.language

    async def list(self, limit: int = 50) -> list[SessionRow]:
        async with self.db.session() as s:
            rows = await s.scalars(select(SessionRow).order_by(SessionRow.started_at.desc())
                                   .limit(limit))
            return list(rows.all())

    async def turns(self, session_id: str) -> list[TranscriptTurn]:
        async with self.db.session() as s:
            rows = await s.scalars(select(TranscriptTurn).where(TranscriptTurn.session_id == session_id)
                                   .order_by(TranscriptTurn.created_at))
            return list(rows.all())


class ConversationManager:
    def __init__(self, *, db: Database, bus: EventBus, audio: AudioEngine, endpoints: EndpointService,
                 rooms: RoomService, router: AIRouter, registry: ToolRegistry,
                 executor: ToolExecutor, jobs: JobQueue, recall: Any) -> None:
        self.db = db
        self.bus = bus
        self.audio = audio
        self.endpoints = endpoints
        self.rooms = rooms
        self.router = router
        self.registry = registry
        self.executor = executor
        self.jobs = jobs
        self.recall = recall
        self.repo = SessionRepository(db)
        self._by_endpoint: dict[str, ConversationSession] = {}
        self._by_id: dict[str, ConversationSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._start_hooks: list[Callable[[ConversationSession], Awaitable[None]]] = []
        audio.set_wake_handler(self._on_wake, lambda ep: ep in self._by_endpoint)

    # ------------------------------------------------------------------ queries
    def get(self, session_id: str) -> ConversationSession | None:
        return self._by_id.get(session_id)

    def for_endpoint(self, endpoint_id: str) -> ConversationSession | None:
        return self._by_endpoint.get(endpoint_id)

    def active(self) -> list[ConversationSession]:
        return list(self._by_id.values())

    def user_turns(self, session_id: str) -> int:
        session = self._by_id.get(session_id)
        return session.user_turns if session else 0

    def on_session_start(self, hook: Callable[[ConversationSession], Awaitable[None]]) -> None:
        self._start_hooks.append(hook)

    # ------------------------------------------------------------------- starts
    async def _on_wake(self, candidate: WakeCandidate, result: ArbitrationResult) -> None:
        existing = self._by_endpoint.get(candidate.endpoint_id)
        if existing is not None:
            existing.sm.activity()  # wakeword during an active session keeps it alive
            return
        try:
            session = await self.start(candidate.endpoint_id, trigger="wakeword")
            # openWakeWord fires while "Jarvis" is still being spoken; skip its tail.
            session.ignore_audio_until(candidate.t + 0.35)
        except Exception as exc:
            log.error("session start failed", endpoint=candidate.endpoint_id, error=str(exc))

    async def start(self, endpoint_id: str, *, trigger: str, instruction: str | None = None,
                    person_id: str | None = None) -> ConversationSession:
        lock = self._locks.setdefault(endpoint_id, asyncio.Lock())
        async with lock:
            existing = self._by_endpoint.get(endpoint_id)
            if existing is not None:
                if instruction:
                    await existing.inject(instruction)
                return existing
            endpoint = await self.endpoints.get(endpoint_id)
            audio_port = self.audio.get(endpoint_id)
            session = await self._create(
                trigger=trigger, endpoint_id=endpoint_id, endpoint_name=endpoint.name,
                room_id=endpoint.room_id, person_id=person_id, audio=audio_port,
                language=endpoint.language,
                default_role=endpoint.config.conversation.default_role,
                endpoint_mode=endpoint.config.conversation.mode,
                timeout_s=endpoint.config.conversation.inactivity_timeout_s,
                end_ms=endpoint.config.conversation.end_of_utterance_silence_ms,
                max_utt_s=endpoint.config.conversation.max_utterance_s,
                has_camera=bool(endpoint.primary(DeviceRole.CAMERA)),
                has_display=bool(endpoint.primary(DeviceRole.DISPLAY)))
            self._by_endpoint[endpoint_id] = session
        await session.start(instruction)
        for hook in self._start_hooks:
            asyncio.create_task(hook(session))
        return session

    async def start_text(self, *, room_id: str | None, user_role: str = "resident",
                         person_id: str | None = None) -> ConversationSession:
        session = await self._create(
            trigger="text", endpoint_id=None, endpoint_name=None, room_id=room_id,
            person_id=person_id, audio=None, language=None, default_role=user_role,
            endpoint_mode=ConversationMode.PIPELINE, timeout_s=600, end_ms=700, max_utt_s=30,
            has_camera=False, has_display=False)
        await session.start()
        return session

    async def _create(self, *, trigger: str, endpoint_id: str | None, endpoint_name: str | None,
                      room_id: str | None, person_id: str | None, audio: Any,
                      language: str | None, default_role: str, endpoint_mode: ConversationMode,
                      timeout_s: float, end_ms: int, max_utt_s: float, has_camera: bool,
                      has_display: bool) -> ConversationSession:
        settings = await self.router.settings()
        rooms = await self.rooms.list()
        room = next((r for r in rooms if r.id == room_id), None)
        person_name, person_role = await self._person(person_id)
        mode = await self._mode(endpoint_mode, audio is not None)
        session_id = new_id("sess")
        ctx = ConversationContext(
            session_id=session_id, endpoint_name=endpoint_name, room_id=room_id,
            room_name=room.name if room else None, person_id=person_id, person_name=person_name,
            language=language or settings.default_language, rooms=[r.name for r in rooms],
            has_camera=has_camera, has_display=has_display, trigger=trigger)
        deps = SessionDeps(router=self.router, registry=self.registry, executor=self.executor,
                           bus=self.bus, store=self.repo, recall=self.recall, settings=settings)
        session = ConversationSession(
            session_id, ctx, deps, audio,
            permissions=conversation_permissions(default_role, person_role),
            mode=mode, inactivity_timeout_s=timeout_s, end_of_utterance_ms=end_ms,
            max_utterance_s=max_utt_s, on_end=self._ended)
        await self.repo.create(session_id, endpoint_id=endpoint_id, room_id=room_id,
                               person_id=person_id, trigger=trigger, mode=mode,
                               language=ctx.language)
        self._by_id[session_id] = session
        return session

    async def _mode(self, endpoint_mode: ConversationMode, has_audio: bool) -> str:
        if not has_audio:
            return "pipeline"
        settings = await self.router.settings()
        wanted = endpoint_mode.value if endpoint_mode != ConversationMode.DEFAULT \
            else settings.conversation_mode.value
        if wanted == GlobalMode.REALTIME and not await self.router.has_realtime():
            log.warning("realtime provider unavailable, using pipeline")
            return "pipeline"
        return wanted

    async def _person(self, person_id: str | None) -> tuple[str | None, str | None]:
        if not person_id:
            return None, None
        async with self.db.session() as s:
            person = await s.get(Person, person_id)
            user = await s.scalar(select(User).where(User.person_id == person_id))
        return (person.name if person else None), (user.role if user and not user.disabled else None)

    async def _ended(self, session: ConversationSession, reason: str) -> None:
        self._by_id.pop(session.id, None)
        if session.endpoint_id and self._by_endpoint.get(session.endpoint_id) is session:
            del self._by_endpoint[session.endpoint_id]
        await self.repo.finish(session.id, reason, person_id=session.ctx.person_id,
                               language=session.ctx.language)
        if session.user_turns:
            await self.jobs.enqueue("memory.extract", {"session_id": session.id},
                                    dedup_key=f"memory.extract:{session.id}", delay_s=2)

    # ------------------------------------------------------------------ control
    async def end(self, session_id: str, reason: str = "manual") -> None:
        session = self._by_id.get(session_id)
        if session is None:
            raise NotFound("session not active")
        await session.end(reason)

    async def end_all(self) -> None:
        for session in list(self._by_id.values()):
            await session.end("shutdown")

    async def ask_text(self, session: ConversationSession, text: str, timeout_s: float = 90) -> str:
        """Send typed text and wait for the assistant's answer (admin chat)."""
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()

        async def listener(role: str, answer: str) -> None:
            if role == "assistant" and not future.done():
                future.set_result(answer)

        session.text_listeners.append(listener)
        try:
            await session.send_text(text)
            return await asyncio.wait_for(future, timeout=timeout_s)
        except TimeoutError as exc:
            raise Unavailable("no answer in time") from exc
        finally:
            session.text_listeners.remove(listener)

    def identify(self, session_id: str, person_id: str, person_name: str) -> None:
        """Bind a recognised/declared person to a running session."""
        session = self._by_id.get(session_id)
        if session is not None:
            session.ctx.person_id = person_id
            session.ctx.person_name = person_name
