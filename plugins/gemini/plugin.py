"""Google Gemini provider: LLM (generate_content) and realtime (Live API)."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
from justai_sdk.audio import AudioChunk
from justai_sdk.plugin import HealthState, Plugin, PluginHealth
from justai_sdk.ports.ai import (
    ChatEvent,
    ChatEventKind,
    ChatMessage,
    ChatRequest,
    Locality,
    ModelInfo,
    RealtimeConfig,
    RealtimeEvent,
    RealtimeEventKind,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)


def _types():  # lazy import keeps plugin import cheap
    from google.genai import types

    return types


def _tools(specs: list[ToolSpec], *, blocking: bool = False) -> list[Any]:
    if not specs:
        return []
    types = _types()
    decls = []
    for t in specs:
        kw: dict[str, Any] = {"name": t.name, "description": t.description,
                              "parameters_json_schema": t.parameters}
        if blocking:
            kw["behavior"] = types.Behavior.BLOCKING
        decls.append(types.FunctionDeclaration(**kw))
    return [types.Tool(function_declarations=decls)]


def _contents(messages: list[ChatMessage]) -> tuple[str, list[Any]]:
    types = _types()
    system: list[str] = []
    contents: list[Any] = []
    pending_responses: list[Any] = []

    def flush_responses() -> None:
        if pending_responses:
            contents.append(types.Content(role="user", parts=list(pending_responses)))
            pending_responses.clear()

    for m in messages:
        if m.role == Role.SYSTEM:
            system.append(m.content)
            continue
        if m.role == Role.TOOL:
            pending_responses.append(types.Part.from_function_response(
                name=m.name or "tool", response=_as_dict(m.content)))
            continue
        flush_responses()
        parts: list[Any] = []
        if m.content:
            parts.append(types.Part(text=m.content))
        for img in m.images:
            parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
        for call in m.tool_calls:
            part = types.Part(function_call=types.FunctionCall(name=call.name, args=call.arguments,
                                                               id=call.id))
            sig = call.provider_data.get("thought_signature")
            if sig:
                part.thought_signature = base64.b64decode(sig)
            parts.append(part)
        if parts:
            contents.append(types.Content(role="model" if m.role == Role.ASSISTANT else "user",
                                          parts=parts))
    flush_responses()
    return "\n\n".join(system), contents


def _as_dict(content: str) -> dict[str, Any]:
    import json

    try:
        value = json.loads(content)
    except (ValueError, TypeError):
        return {"result": content}
    return value if isinstance(value, dict) else {"result": value}


class GeminiLLM:
    provider_id = "gemini"
    locality = Locality.CLOUD

    def __init__(self, client: Any) -> None:
        self.client = client

    async def chat(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        types = _types()
        system, contents = _contents(request.messages)
        config: dict[str, Any] = {}
        if system:
            config["system_instruction"] = system
        if request.tools:
            config["tools"] = _tools(request.tools)
            config["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        if request.json_schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = request.json_schema
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.max_tokens:
            config["max_output_tokens"] = request.max_tokens
        stream = await self.client.aio.models.generate_content_stream(
            model=request.model, contents=contents,
            config=types.GenerateContentConfig(**config))
        usage = Usage()
        async for chunk in stream:
            if chunk.usage_metadata:
                usage = Usage(input_tokens=chunk.usage_metadata.prompt_token_count or 0,
                              output_tokens=chunk.usage_metadata.candidates_token_count or 0)
            for cand in chunk.candidates or []:
                for part in (cand.content.parts if cand.content else None) or []:
                    if part.thought:
                        continue
                    if part.function_call:
                        fc = part.function_call
                        data: dict[str, Any] = {}
                        if part.thought_signature:
                            data["thought_signature"] = base64.b64encode(part.thought_signature).decode()
                        yield ChatEvent(kind=ChatEventKind.TOOL_CALL, tool_call=ToolCall(
                            id=fc.id or f"call_{uuid.uuid4().hex[:12]}", name=fc.name or "",
                            arguments=dict(fc.args or {}), provider_data=data))
                    elif part.text:
                        yield ChatEvent(kind=ChatEventKind.TEXT, text=part.text)
        yield ChatEvent(kind=ChatEventKind.DONE, usage=usage)

    async def list_models(self) -> list[ModelInfo]:
        out = []
        async for m in await self.client.aio.models.list():
            actions = m.supported_actions or []
            if "generateContent" in actions:
                out.append(ModelInfo(id=m.name.removeprefix("models/"), name=m.display_name or "",
                                     supports_vision=True))
        return out


class GeminiRealtimeSession:
    def __init__(self, cm: Any, session: Any) -> None:
        self._cm = cm
        self._session = session
        self._closed = False

    async def send_audio(self, chunk: AudioChunk) -> None:
        types = _types()
        await self._session.send_realtime_input(
            audio=types.Blob(data=chunk.to_bytes(), mime_type=f"audio/pcm;rate={chunk.sample_rate}"))

    async def send_image(self, jpeg: bytes) -> None:
        types = _types()
        await self._session.send_realtime_input(video=types.Blob(data=jpeg, mime_type="image/jpeg"))

    async def send_text(self, text: str, *, end_of_turn: bool = True) -> None:
        types = _types()
        await self._session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]), turn_complete=end_of_turn)

    async def send_tool_result(self, call: ToolCall, result: dict[str, Any]) -> None:
        types = _types()
        await self._session.send_tool_response(function_responses=[
            types.FunctionResponse(id=call.id, name=call.name, response=result)])

    async def events(self) -> AsyncIterator[RealtimeEvent]:
        try:
            while not self._closed:
                async for msg in self._session.receive():
                    for ev in self._map(msg):
                        yield ev
        except Exception as exc:  # connection closed / API error
            if not self._closed:
                yield RealtimeEvent(kind=RealtimeEventKind.ERROR, error=str(exc))
        yield RealtimeEvent(kind=RealtimeEventKind.CLOSED)

    def _map(self, msg: Any) -> list[RealtimeEvent]:
        out: list[RealtimeEvent] = []
        sc = msg.server_content
        if sc is not None:
            if sc.model_turn and sc.model_turn.parts:
                for part in sc.model_turn.parts:
                    blob = part.inline_data
                    if blob and blob.data and (blob.mime_type or "").startswith("audio/pcm"):
                        rate = 24000
                        if "rate=" in (blob.mime_type or ""):
                            rate = int(blob.mime_type.split("rate=")[1].split(";")[0])
                        pcm = np.frombuffer(blob.data, dtype="<i2").astype(np.int16)
                        out.append(RealtimeEvent(kind=RealtimeEventKind.AUDIO,
                                                 audio=AudioChunk(pcm, rate)))
            if sc.input_transcription and sc.input_transcription.text:
                out.append(RealtimeEvent(kind=RealtimeEventKind.INPUT_TRANSCRIPT,
                                         text=sc.input_transcription.text,
                                         final=bool(sc.input_transcription.finished)))
            if sc.output_transcription and sc.output_transcription.text:
                out.append(RealtimeEvent(kind=RealtimeEventKind.OUTPUT_TRANSCRIPT,
                                         text=sc.output_transcription.text,
                                         final=bool(sc.output_transcription.finished)))
            if sc.interrupted:
                out.append(RealtimeEvent(kind=RealtimeEventKind.INTERRUPTED))
            if sc.turn_complete:
                out.append(RealtimeEvent(kind=RealtimeEventKind.TURN_COMPLETE))
        if msg.tool_call and msg.tool_call.function_calls:
            for fc in msg.tool_call.function_calls:
                out.append(RealtimeEvent(kind=RealtimeEventKind.TOOL_CALL, tool_call=ToolCall(
                    id=fc.id or f"call_{uuid.uuid4().hex[:12]}", name=fc.name or "",
                    arguments=dict(fc.args or {}))))
        if msg.tool_call_cancellation and msg.tool_call_cancellation.ids:
            for cid in msg.tool_call_cancellation.ids:
                out.append(RealtimeEvent(kind=RealtimeEventKind.TOOL_CALL_CANCELLED, text=cid))
        if msg.usage_metadata:
            u = msg.usage_metadata
            out.append(RealtimeEvent(kind=RealtimeEventKind.USAGE, usage=Usage(
                input_tokens=u.prompt_token_count or 0,
                output_tokens=u.response_token_count or 0)))
        if msg.go_away:
            out.append(RealtimeEvent(kind=RealtimeEventKind.ERROR, error="server requested reconnect"))
        return out

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with contextlib.suppress(Exception):
            await self._cm.__aexit__(None, None, None)


BCP47 = {"de": "de-DE", "it": "it-IT", "en": "en-US", "fr": "fr-FR", "es": "es-ES"}


class GeminiRealtime:
    provider_id = "gemini"
    locality = Locality.CLOUD

    def __init__(self, client: Any, default_voice: str, silence_ms: int) -> None:
        self.client = client
        self.default_voice = default_voice
        self.silence_ms = silence_ms

    async def connect(self, config: RealtimeConfig) -> GeminiRealtimeSession:
        types = _types()
        live_config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            system_instruction=config.instructions or None,
            tools=_tools(config.tools, blocking=True) or None,
            speech_config=types.SpeechConfig(language_code=config.language or None, voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=config.voice or self.default_voice))),
            input_audio_transcription=types.AudioTranscriptionConfig(
                language_codes=[BCP47.get(x, x) for x in config.languages] or None,
                custom_vocabulary=config.vocabulary or None) if config.transcribe_input else None,
            output_audio_transcription=types.AudioTranscriptionConfig() if config.transcribe_output else None,
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    silence_duration_ms=self.silence_ms, prefix_padding_ms=300,
                    # A short pause to think must not end the user's turn: with a half-duplex
                    # camera the rest of the sentence would fall into the echo gate.
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_LOW)),
        )
        cm = self.client.aio.live.connect(model=config.model, config=live_config)
        session = await cm.__aenter__()
        return GeminiRealtimeSession(cm, session)

    async def list_models(self) -> list[ModelInfo]:
        out = []
        async for m in await self.client.aio.models.list():
            if "bidiGenerateContent" in (m.supported_actions or []):
                out.append(ModelInfo(id=m.name.removeprefix("models/"), name=m.display_name or "",
                                     supports_audio=True))
        return out


class GeminiPlugin(Plugin):
    async def setup(self) -> None:
        from google import genai

        key = self.ctx.config.get("api_key") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            self.ctx.logger.warning("no Gemini API key configured; provider not registered")
            self.client = None
            return
        from google.genai import types

        # No SDK-internal retries: JuStAI's AI router falls back to the next provider
        # immediately, which is much faster than retrying an overloaded model.
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=60_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.ctx.register_provider("llm", GeminiLLM(self.client))
        self.ctx.register_provider("realtime", GeminiRealtime(
            self.client, self.ctx.config.get("default_voice", "Kore"),
            int(self.ctx.config.get("vad_silence_ms", 1000))))

    async def health(self) -> PluginHealth:
        if self.client is None:
            return PluginHealth(state=HealthState.DEGRADED, detail="API key missing")
        try:
            await asyncio.wait_for(self.client.aio.models.get(model="gemini-3.8-flash"), 10)
        except Exception as exc:
            return PluginHealth(state=HealthState.DEGRADED, detail=f"API check failed: {exc}")
        return PluginHealth()
