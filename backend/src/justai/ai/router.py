"""AI router: resolves a task role to a provider chain and enforces privacy rules.

* Candidates are taken from the role's chain in order (primary, then fallbacks).
* Cloud providers are skipped if the role is ``local_only``, if cloud use is
  disabled globally, if the payload contains data the policy keeps local (camera
  images, personal memories, conversation audio), or if the cost limit is reached.
* Falling back to another provider publishes ``ai.provider.fallback``; a switch
  from local to cloud is additionally written to the audit log - it never happens
  silently.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from justai_sdk.audio import AudioChunk
from justai_sdk.events import Event
from justai_sdk.ports.ai import (
    ChatEvent,
    ChatEventKind,
    ChatMessage,
    ChatRequest,
    Locality,
    RealtimeConfig,
    RealtimeSession,
    ToolCall,
    ToolSpec,
    Transcription,
    Usage,
)

from justai.ai.config import AISettings, Locality as RoleLocality, ModelRef, ModelRole
from justai.ai.usage import UsageTracker
from justai.common.errors import PolicyViolation, Unavailable
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.plugins.providers import ProviderRegistry

log = get_logger(__name__)

KIND_FOR_ROLE: dict[ModelRole, str] = {
    ModelRole.CONVERSATION: "llm",
    ModelRole.REASONING: "llm",
    ModelRole.VISION: "llm",
    ModelRole.MEMORY: "llm",
    ModelRole.TOOL_GENERATION: "llm",
    ModelRole.BACKGROUND: "llm",
    ModelRole.REALTIME: "realtime",
    ModelRole.STT: "stt",
    ModelRole.TTS: "tts",
    ModelRole.EMBEDDING: "embedding",
}

# Roles without a configured chain borrow the chain of another role.
ROLE_FALLBACK: dict[ModelRole, ModelRole] = {
    ModelRole.REASONING: ModelRole.CONVERSATION,
    ModelRole.VISION: ModelRole.CONVERSATION,
    ModelRole.MEMORY: ModelRole.BACKGROUND,
    ModelRole.TOOL_GENERATION: ModelRole.REASONING,
    ModelRole.BACKGROUND: ModelRole.CONVERSATION,
}


@dataclass(frozen=True)
class DataFlags:
    """What kind of data a request contains (for privacy decisions)."""

    personal: bool = False
    images: bool = False
    audio: bool = False
    local_only: bool = False  # e.g. camera images of a room that forbids cloud media


@dataclass
class Candidate:
    ref: ModelRef
    provider: Any
    locality: Locality


@dataclass
class ChatResult:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    provider: str = ""
    model: str = ""


SettingsLoader = Callable[[], Awaitable[AISettings]]
AuditHook = Callable[[str, dict[str, Any]], Awaitable[None]]


class AIRouter:
    def __init__(self, providers: ProviderRegistry, load_settings: SettingsLoader, bus: EventBus,
                 usage: UsageTracker, audit: AuditHook | None = None) -> None:
        self.providers = providers
        self._load_settings = load_settings
        self.bus = bus
        self.usage = usage
        self.audit = audit
        self._settings: AISettings | None = None
        # (provider, model) -> monotonic time until which it is skipped after overload errors
        self._cooldown: dict[tuple[str, str], float] = {}

    COOLDOWN_S = 60.0
    FIRST_TOKEN_TIMEOUT_S = 25.0

    def _cool(self, cand: Candidate, error: BaseException) -> None:
        text = f"{type(error).__name__} {error}"
        if isinstance(error, TimeoutError) or any(code in text for code in ("503", "429", "UNAVAILABLE",
                                                                             "RESOURCE_EXHAUSTED")):
            self._cooldown[(cand.ref.provider, cand.ref.model)] = time.monotonic() + self.COOLDOWN_S

    def _ordered(self, candidates: list[Candidate]) -> list[Candidate]:
        """Candidates in configured order, but recently overloaded ones last."""
        now = time.monotonic()
        fresh = [c for c in candidates if self._cooldown.get((c.ref.provider, c.ref.model), 0) <= now]
        cooled = [c for c in candidates if c not in fresh]
        return fresh + cooled

    def cooldowns(self) -> dict[str, float]:
        now = time.monotonic()
        return {f"{p}/{m}": round(until - now, 1) for (p, m), until in self._cooldown.items() if until > now}

    async def settings(self) -> AISettings:
        if self._settings is None:
            self._settings = await self._load_settings()
        return self._settings

    def invalidate(self) -> None:
        self._settings = None

    # ---------------------------------------------------------------- candidates
    async def candidates(self, role: ModelRole, flags: DataFlags = DataFlags()) -> tuple[list[Candidate], list[str]]:
        """Usable providers for a role, plus human readable reasons for skipped ones."""
        settings = await self.settings()
        role_cfg = settings.role(role)
        # Roles without an own chain borrow one (e.g. memory -> background ->
        # conversation). The requesting role's locality rule always applies.
        source, chain = role, role_cfg.chain
        while not chain and source in ROLE_FALLBACK:
            source = ROLE_FALLBACK[source]
            chain = settings.role(source).chain
        kind = KIND_FOR_ROLE[role]
        usable: list[Candidate] = []
        skipped: list[str] = []
        for ref in chain:
            provider = self.providers.get(kind, ref.provider)
            if provider is None:
                skipped.append(f"{ref.provider}: not available")
                continue
            locality = Locality(getattr(provider, "locality", Locality.CLOUD))
            if locality == Locality.CLOUD:
                reason = self._cloud_block_reason(settings, role_cfg.locality, flags)
                if reason:
                    skipped.append(f"{ref.provider}: {reason}")
                    continue
            usable.append(Candidate(ref, provider, locality))
        return usable, skipped

    def _cloud_block_reason(self, s: AISettings, locality: RoleLocality, flags: DataFlags) -> str | None:
        if locality == RoleLocality.LOCAL_ONLY:
            return "role is restricted to local processing"
        if flags.local_only:
            return "data must stay local (room policy)"
        p = s.privacy
        if not p.cloud_allowed:
            return "cloud AI is disabled"
        if flags.images and not p.camera_images_to_cloud:
            return "camera images must stay local"
        if flags.personal and not p.personal_memories_to_cloud:
            return "personal data must stay local"
        if flags.audio and not p.conversation_audio_to_cloud:
            return "conversation audio must stay local"
        if s.cost_limits.daily_usd is not None and self.usage.today_cost_usd >= s.cost_limits.daily_usd:
            return "daily cost limit reached"
        return None

    async def _require(self, role: ModelRole, flags: DataFlags) -> list[Candidate]:
        usable, skipped = await self.candidates(role, flags)
        if not usable:
            detail = "; ".join(skipped) or "no provider configured"
            raise (PolicyViolation if any("local" in s or "disabled" in s for s in skipped)
                   else Unavailable)(f"no AI provider for {role}: {detail}")
        return usable

    async def _fallback_used(self, role: ModelRole, failed: Candidate, used: Candidate,
                             error: str) -> None:
        settings = await self.settings()
        to_cloud = failed.locality == Locality.LOCAL and used.locality == Locality.CLOUD
        payload = {"role": role, "from": f"{failed.ref.provider}/{failed.ref.model}",
                   "to": f"{used.ref.provider}/{used.ref.model}", "error": error[:300],
                   "local_to_cloud": to_cloud}
        await self.bus.publish(Event(type="ai.provider.fallback", payload=payload))
        if to_cloud and settings.privacy.announce_cloud_fallback and self.audit:
            await self.audit("ai.cloud_fallback", payload)

    # ---------------------------------------------------------------------- LLM
    async def chat(self, role: ModelRole, messages: list[ChatMessage], *,
                   tools: list[ToolSpec] | None = None, json_schema: dict[str, Any] | None = None,
                   flags: DataFlags = DataFlags(), temperature: float | None = None,
                   max_tokens: int | None = None) -> ChatResult:
        candidates = self._ordered(await self._require(role, flags))
        settings = await self.settings()
        timeout = settings.role(role).timeout_s
        first: Candidate | None = None
        last_error = ""
        for cand in candidates:
            started = time.monotonic()
            req = ChatRequest(model=cand.ref.model, messages=messages, tools=tools or [],
                              json_schema=json_schema, timeout_s=timeout,
                              temperature=cand.ref.options.get("temperature", temperature),
                              max_tokens=max_tokens)
            try:
                result = await asyncio.wait_for(self._collect(cand, req), timeout=timeout)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                self._cool(cand, exc)
                log.warning("llm provider failed", role=role, provider=cand.ref.provider,
                            model=cand.ref.model, error=last_error[:200])
                self.usage.record(provider=cand.ref.provider, model=cand.ref.model, role=role,
                                  ok=False, latency_ms=int((time.monotonic() - started) * 1000))
                first = first or cand
                continue
            u = result.usage or Usage()
            self.usage.record(provider=cand.ref.provider, model=cand.ref.model, role=role, ok=True,
                              input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                              latency_ms=int((time.monotonic() - started) * 1000),
                              cost_usd=u.cost_usd)
            if first is not None:
                await self._fallback_used(role, first, cand, last_error)
            return result
        raise Unavailable(f"all providers failed for {role}: {last_error}")

    async def _collect(self, cand: Candidate, req: ChatRequest) -> ChatResult:
        text: list[str] = []
        calls: list[ToolCall] = []
        usage: Usage | None = None
        async for ev in cand.provider.chat(req):
            if ev.kind == ChatEventKind.TEXT:
                text.append(ev.text)
            elif ev.kind == ChatEventKind.TOOL_CALL and ev.tool_call:
                calls.append(ev.tool_call)
            elif ev.kind == ChatEventKind.DONE:
                usage = ev.usage
        return ChatResult("".join(text), calls, usage, cand.ref.provider, cand.ref.model)

    async def stream_chat(self, role: ModelRole, messages: list[ChatMessage], *,
                          tools: list[ToolSpec] | None = None,
                          flags: DataFlags = DataFlags()) -> AsyncIterator[ChatEvent]:
        """Streaming chat. Falls back only if a provider fails (or stays silent for
        FIRST_TOKEN_TIMEOUT_S) before producing output."""
        candidates = self._ordered(await self._require(role, flags))
        settings = await self.settings()
        total_timeout = settings.role(role).timeout_s
        first: Candidate | None = None
        last_error = ""
        for cand in candidates:
            started = time.monotonic()
            produced = False
            req = ChatRequest(model=cand.ref.model, messages=messages, tools=tools or [],
                              timeout_s=total_timeout,
                              temperature=cand.ref.options.get("temperature"))
            stream = cand.provider.chat(req).__aiter__()
            try:
                while True:
                    budget = (self.FIRST_TOKEN_TIMEOUT_S if not produced
                              else max(1.0, total_timeout - (time.monotonic() - started)))
                    try:
                        ev = await asyncio.wait_for(stream.__anext__(), timeout=budget)
                    except StopAsyncIteration:
                        return
                    if not produced and first is not None:
                        await self._fallback_used(role, first, cand, last_error)
                    produced = True
                    if ev.kind == ChatEventKind.DONE:
                        u = ev.usage or Usage()
                        self.usage.record(provider=cand.ref.provider, model=cand.ref.model,
                                          role=role, ok=True, input_tokens=u.input_tokens,
                                          output_tokens=u.output_tokens, cost_usd=u.cost_usd,
                                          latency_ms=int((time.monotonic() - started) * 1000))
                    yield ev
            except Exception as exc:
                if produced:
                    raise
                last_error = f"{type(exc).__name__}: {exc}"
                self._cool(cand, exc)
                log.warning("llm stream failed", provider=cand.ref.provider, model=cand.ref.model,
                            error=last_error[:200])
                self.usage.record(provider=cand.ref.provider, model=cand.ref.model, role=role, ok=False)
                first = first or cand
            finally:
                with contextlib.suppress(Exception):
                    await stream.aclose()  # type: ignore[attr-defined]
        raise Unavailable(f"all providers failed for {role}: {last_error[:300]}")

    # ----------------------------------------------------------------- realtime
    async def connect_realtime(self, config: RealtimeConfig, flags: DataFlags = DataFlags(audio=True)
                               ) -> tuple[RealtimeSession, Candidate]:
        candidates = await self._require(ModelRole.REALTIME, flags)
        last_error = ""
        first: Candidate | None = None
        for cand in candidates:
            cfg = config.model_copy(update={"model": cand.ref.model or config.model,
                                            "voice": cand.ref.options.get("voice", config.voice)})
            try:
                session = await asyncio.wait_for(cand.provider.connect(cfg), timeout=15)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("realtime connect failed", provider=cand.ref.provider, error=last_error)
                first = first or cand
                continue
            if first is not None:
                await self._fallback_used(ModelRole.REALTIME, first, cand, last_error)
            self.usage.record(provider=cand.ref.provider, model=cfg.model, role="realtime", ok=True)
            return session, cand
        raise Unavailable(f"no realtime provider available: {last_error}")

    async def has_realtime(self) -> bool:
        usable, _ = await self.candidates(ModelRole.REALTIME, DataFlags(audio=True))
        return bool(usable)

    # ---------------------------------------------------------------- STT / TTS
    async def transcribe(self, audio: AudioChunk, *, language: str | None = None,
                         prompt: str | None = None) -> Transcription:
        candidates = await self._require(ModelRole.STT, DataFlags(audio=True, personal=True))
        last_error = ""
        for i, cand in enumerate(candidates):
            started = time.monotonic()
            try:
                result: Transcription = await cand.provider.transcribe(audio, language=language,
                                                                        prompt=prompt)
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                continue
            self.usage.record(provider=cand.ref.provider, model=cand.ref.model, role="stt", ok=True,
                              audio_seconds=audio.duration_s,
                              latency_ms=int((time.monotonic() - started) * 1000))
            if i > 0:
                await self._fallback_used(ModelRole.STT, candidates[0], cand, last_error)
            return result
        raise Unavailable(f"speech recognition failed: {last_error}")

    async def synthesize(self, text: str, *, language: str | None = None,
                         voice: str | None = None) -> AsyncIterator[AudioChunk]:
        settings = await self.settings()
        candidates = await self._require(ModelRole.TTS, DataFlags(personal=True))
        lang = (language or settings.default_language)[:2]
        last_error = ""
        for cand in candidates:
            chosen_voice = voice or cand.ref.options.get(f"voice_{lang}") or settings.voices.get(lang)
            produced = False
            try:
                async for chunk in cand.provider.synthesize(text, voice=chosen_voice, language=lang):
                    produced = True
                    yield chunk
                return
            except Exception as exc:
                if produced:
                    raise
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning("tts failed", provider=cand.ref.provider, error=last_error)
        raise Unavailable(f"speech synthesis failed: {last_error}")

    # --------------------------------------------------------------- embeddings
    async def embedder(self) -> Any:
        candidates = await self._require(ModelRole.EMBEDDING, DataFlags(personal=True))
        return candidates[0].provider

    async def embed(self, texts: list[str], *, kind: str = "document") -> tuple[list[list[float]], str]:
        provider = await self.embedder()
        vectors = await provider.embed(texts, kind=kind)
        return vectors, provider.model_id

    # ----------------------------------------------------------------- overview
    async def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for role in ModelRole:
            usable, skipped = await self.candidates(role)
            out[role.value] = {
                "usable": [{"provider": c.ref.provider, "model": c.ref.model,
                            "locality": c.locality.value} for c in usable],
                "skipped": skipped,
            }
        out["_cooldowns"] = self.cooldowns()
        return out
