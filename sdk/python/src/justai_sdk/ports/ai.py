"""AI provider ports: LLM, realtime speech models, STT, TTS and embeddings.

Providers declare their ``locality`` so that the core can enforce privacy
policies (e.g. "personal data must stay local") before any data leaves the host.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from justai_sdk.audio import AudioChunk


class Locality(StrEnum):
    LOCAL = "local"  # runs on this host / in the LAN
    CLOUD = "cloud"  # sends data to an external service


# --------------------------------------------------------------------------- LLM


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ImagePart(BaseModel):
    data: bytes
    mime_type: str = "image/jpeg"


class ToolCall(BaseModel):
    id: str
    name: str  # tool name as exposed to the model (llm_name)
    arguments: dict[str, Any] = Field(default_factory=dict)
    # Opaque provider data that must be sent back with the call (e.g. Gemini
    # thought signatures). Providers own its format.
    provider_data: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Role
    content: str = ""
    images: list[ImagePart] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    tools: list[ToolSpec] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    json_schema: dict[str, Any] | None = None  # request structured JSON output
    timeout_s: float = 60.0


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


class ChatEventKind(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    DONE = "done"


class ChatEvent(BaseModel):
    kind: ChatEventKind
    text: str = ""
    tool_call: ToolCall | None = None
    usage: Usage | None = None


class ModelInfo(BaseModel):
    id: str
    name: str = ""
    supports_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False


@runtime_checkable
class LLMProvider(Protocol):
    provider_id: str
    locality: Locality

    def chat(self, request: ChatRequest) -> AsyncIterator[ChatEvent]: ...

    async def list_models(self) -> list[ModelInfo]: ...


# --------------------------------------------------------------- realtime speech


class RealtimeConfig(BaseModel):
    model: str
    instructions: str = ""
    voice: str | None = None
    language: str | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    input_sample_rate: int = 16000
    transcribe_input: bool = True
    transcribe_output: bool = True


class RealtimeEventKind(StrEnum):
    AUDIO = "audio"  # model speech
    INPUT_TRANSCRIPT = "input_transcript"
    OUTPUT_TRANSCRIPT = "output_transcript"
    TOOL_CALL = "tool_call"
    TOOL_CALL_CANCELLED = "tool_call_cancelled"
    RESPONSE_STARTED = "response_started"
    TURN_COMPLETE = "turn_complete"
    INTERRUPTED = "interrupted"  # server-side barge-in
    USAGE = "usage"
    ERROR = "error"
    CLOSED = "closed"


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: RealtimeEventKind
    audio: AudioChunk | None = None
    text: str = ""
    final: bool = False
    tool_call: ToolCall | None = None
    usage: Usage | None = None
    error: str | None = None


class RealtimeSession(Protocol):
    async def send_audio(self, chunk: AudioChunk) -> None: ...

    async def send_image(self, jpeg: bytes) -> None: ...

    async def send_text(self, text: str, *, end_of_turn: bool = True) -> None: ...

    async def send_tool_result(self, call: ToolCall, result: dict[str, Any]) -> None: ...

    def events(self) -> AsyncIterator[RealtimeEvent]: ...

    async def close(self) -> None: ...


@runtime_checkable
class RealtimeProvider(Protocol):
    provider_id: str
    locality: Locality

    async def connect(self, config: RealtimeConfig) -> RealtimeSession: ...

    async def list_models(self) -> list[ModelInfo]: ...


# ------------------------------------------------------------------- STT / TTS


class Transcription(BaseModel):
    text: str
    language: str | None = None
    language_probability: float | None = None
    no_speech_probability: float | None = None
    duration_s: float = 0.0


@runtime_checkable
class STTProvider(Protocol):
    provider_id: str
    locality: Locality

    async def transcribe(
        self, audio: AudioChunk, *, language: str | None = None, prompt: str | None = None
    ) -> Transcription: ...


class VoiceInfo(BaseModel):
    id: str
    name: str
    language: str
    gender: str | None = None


@runtime_checkable
class TTSProvider(Protocol):
    provider_id: str
    locality: Locality

    def synthesize(
        self, text: str, *, voice: str | None = None, language: str | None = None
    ) -> AsyncIterator[AudioChunk]: ...

    async def list_voices(self) -> list[VoiceInfo]: ...


# ------------------------------------------------------------------ embeddings


@runtime_checkable
class EmbeddingProvider(Protocol):
    provider_id: str
    locality: Locality
    model_id: str
    dimension: int

    async def embed(self, texts: list[str], *, kind: str = "document") -> list[list[float]]: ...
