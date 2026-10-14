"""OpenAI-compatible chat/STT/TTS endpoints (OpenAI, Ollama, vLLM, llama.cpp, ...)."""

from __future__ import annotations

import base64
import io
import json
import wave
from collections.abc import AsyncIterator
from typing import Any

import numpy as np
from justai_sdk.audio import AudioChunk
from justai_sdk.plugin import Plugin, PluginHealth, HealthState
from justai_sdk.ports.ai import (
    ChatEvent,
    ChatEventKind,
    ChatMessage,
    ChatRequest,
    Locality,
    ModelInfo,
    Role,
    ToolCall,
    Transcription,
    Usage,
    VoiceInfo,
)


def to_openai_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == Role.TOOL:
            out.append({"role": "tool", "tool_call_id": m.tool_call_id or "", "content": m.content})
            continue
        msg: dict[str, Any] = {"role": m.role.value}
        if m.images:
            parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}] if m.content else []
            for img in m.images:
                b64 = base64.b64encode(img.data).decode()
                parts.append({"type": "image_url",
                              "image_url": {"url": f"data:{img.mime_type};base64,{b64}"}})
            msg["content"] = parts
        else:
            msg["content"] = m.content
        if m.tool_calls:
            msg["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                                 for c in m.tool_calls]
        out.append(msg)
    return out


class OpenAICompatLLM:
    locality: Locality

    def __init__(self, endpoint: dict[str, Any], api_key: str | None) -> None:
        from openai import AsyncOpenAI

        self.provider_id = f"oai:{endpoint['id']}"
        self.locality = Locality(endpoint.get("locality", "cloud"))
        self.supports_tools = bool(endpoint.get("supports_tools", True))
        self.client = AsyncOpenAI(base_url=endpoint["base_url"], api_key=api_key or "not-needed")

    async def chat(self, request: ChatRequest) -> AsyncIterator[ChatEvent]:
        kwargs: dict[str, Any] = {"model": request.model, "stream": True,
                                  "messages": to_openai_messages(request.messages),
                                  "stream_options": {"include_usage": True},
                                  "timeout": request.timeout_s}
        if request.tools and self.supports_tools:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in request.tools]
        if request.json_schema is not None:
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {
                "name": "result", "schema": request.json_schema}}
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens:
            kwargs["max_tokens"] = request.max_tokens
        stream = await self.client.chat.completions.create(**kwargs)
        calls: dict[int, dict[str, Any]] = {}
        usage = Usage()
        async for chunk in stream:
            if chunk.usage:
                usage = Usage(input_tokens=chunk.usage.prompt_tokens or 0,
                              output_tokens=chunk.usage.completion_tokens or 0)
            for choice in chunk.choices:
                delta = choice.delta
                if delta.content:
                    yield ChatEvent(kind=ChatEventKind.TEXT, text=delta.content)
                for tc in delta.tool_calls or []:
                    entry = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    entry["id"] = tc.id or entry["id"]
                    if tc.function:
                        entry["name"] += tc.function.name or ""
                        entry["args"] += tc.function.arguments or ""
        for i, entry in sorted(calls.items()):
            try:
                args = json.loads(entry["args"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": entry["args"]}
            yield ChatEvent(kind=ChatEventKind.TOOL_CALL, tool_call=ToolCall(
                id=entry["id"] or f"call_{i}", name=entry["name"], arguments=args))
        yield ChatEvent(kind=ChatEventKind.DONE, usage=usage)

    async def list_models(self) -> list[ModelInfo]:
        models = await self.client.models.list()
        return [ModelInfo(id=m.id, name=m.id) async for m in models]


class OpenAICompatSTT:
    def __init__(self, llm: OpenAICompatLLM, model: str = "gpt-4o-mini-transcribe") -> None:
        self.provider_id = llm.provider_id
        self.locality = llm.locality
        self.client = llm.client
        self.model = model

    async def transcribe(self, audio: AudioChunk, *, language: str | None = None,
                         prompt: str | None = None) -> Transcription:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.sample_rate)
            w.writeframes(audio.to_bytes())
        kwargs: dict[str, Any] = {"model": self.model, "file": ("speech.wav", buf.getvalue())}
        if language:
            kwargs["language"] = language
        if prompt:
            kwargs["prompt"] = prompt
        result = await self.client.audio.transcriptions.create(**kwargs)
        return Transcription(text=result.text, language=language, duration_s=audio.duration_s)


class OpenAICompatTTS:
    def __init__(self, llm: OpenAICompatLLM, model: str = "gpt-4o-mini-tts") -> None:
        self.provider_id = llm.provider_id
        self.locality = llm.locality
        self.client = llm.client
        self.model = model

    async def synthesize(self, text: str, *, voice: str | None = None,
                         language: str | None = None) -> AsyncIterator[AudioChunk]:
        response = await self.client.audio.speech.create(
            model=self.model, voice=voice or "alloy", input=text, response_format="pcm")
        pcm = np.frombuffer(response.content, dtype="<i2").astype(np.int16)
        yield AudioChunk(pcm, 24000)

    async def list_voices(self) -> list[VoiceInfo]:
        return [VoiceInfo(id=v, name=v, language="multi")
                for v in ("alloy", "ash", "coral", "echo", "nova", "sage", "shimmer")]


class OpenAICompatPlugin(Plugin):
    async def setup(self) -> None:
        keys: dict[str, str] = {}
        raw = self.ctx.config.get("api_keys")
        if raw:
            try:
                keys = json.loads(raw)
            except json.JSONDecodeError:
                self.ctx.logger.warning("api_keys is not valid JSON")
        self.llms: list[OpenAICompatLLM] = []
        for ep in self.ctx.config.get("endpoints", []):
            llm = OpenAICompatLLM(ep, keys.get(ep["id"]))
            self.llms.append(llm)
            self.ctx.register_provider("llm", llm)
            if ep.get("stt"):
                self.ctx.register_provider("stt", OpenAICompatSTT(llm))
            if ep.get("tts"):
                self.ctx.register_provider("tts", OpenAICompatTTS(llm))

    async def health(self) -> PluginHealth:
        failing = []
        for llm in self.llms:
            try:
                await llm.client.models.list(timeout=5)
            except Exception as exc:
                failing.append(f"{llm.provider_id}: {type(exc).__name__}")
        if failing:
            return PluginHealth(state=HealthState.DEGRADED, detail="; ".join(failing))
        return PluginHealth()
