from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, UploadFile

from justai.ai.config import AISettings
from justai.api.deps import Admin, C, User
from justai.common.errors import Conflict, Unavailable, ValidationFailed

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.get("/settings")
async def get_settings(_: User, c: C) -> dict[str, Any]:
    return (await c.ai.settings()).model_dump(mode="json")


@router.put("/settings")
async def put_settings(body: AISettings, p: Admin, c: C) -> dict[str, Any]:
    await c.settings_store.set("ai", body)
    c.ai.invalidate()
    await c.audit.record(p.actor, "ai.settings.update", None,
                         privacy=body.privacy.model_dump(), mode=body.conversation_mode)
    return body.model_dump(mode="json")


@router.get("/status")
async def status(_: User, c: C) -> dict[str, Any]:
    return {"roles": await c.ai.status(), "cooldowns": c.ai.cooldowns(),
            "today_cost_usd": round(c.usage.today_cost_usd, 4)}


@router.get("/providers")
async def providers(_: User, c: C) -> list[dict[str, Any]]:
    out = []
    for kind in ("llm", "realtime", "stt", "tts", "embedding", "wakeword"):
        for entry in c.providers.entries(kind):
            out.append({"kind": kind, "id": entry.id, "plugin_id": entry.plugin_id,
                        "locality": str(getattr(entry.provider, "locality", "local"))})
    return out


@router.get("/providers/{kind}/{provider_id}/models")
async def models(kind: str, provider_id: str, _: Admin, c: C) -> list[dict[str, Any]]:
    provider = c.providers.get(kind, provider_id)
    if provider is None:
        return []
    if kind == "tts":
        return [v.model_dump() for v in await provider.list_voices()]
    if kind == "wakeword":
        return [m.model_dump() for m in provider.list_models()]
    with contextlib.suppress(Exception):
        return [m.model_dump() for m in await provider.list_models()]
    return []


@router.post("/wakewords")
async def upload_wakeword(file: UploadFile, p: Admin, c: C) -> dict[str, str]:
    """Install a custom openWakeWord model (.onnx), e.g. trained for "Hey Justi"."""
    provider = c.providers.get("wakeword", "openwakeword")
    if provider is None or not hasattr(provider, "install_model"):
        raise Unavailable("openWakeWord plugin is not running")
    data = await file.read(20_000_001)
    try:
        mid = await asyncio.to_thread(provider.install_model, file.filename or "", data)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    await c.audit.record(p.actor, "wakeword.install", mid, size=len(data))
    return {"id": mid}


@router.delete("/wakewords/{model_id}")
async def delete_wakeword(model_id: str, p: Admin, c: C) -> dict[str, bool]:
    provider = c.providers.get("wakeword", "openwakeword")
    if provider is None or not hasattr(provider, "remove_model"):
        raise Unavailable("openWakeWord plugin is not running")
    in_use = [e.name for e in await c.endpoints.list() if model_id in e.config.wakeword.models]
    if in_use:
        raise Conflict(f"model is used by endpoints: {', '.join(in_use)}")
    try:
        provider.remove_model(model_id)
    except ValueError as exc:
        raise ValidationFailed(str(exc)) from exc
    await c.audit.record(p.actor, "wakeword.delete", model_id)
    return {"ok": True}


@router.get("/usage")
async def usage(_: Admin, c: C) -> list[dict[str, Any]]:
    return [{"day": u.day, "provider": u.provider, "model": u.model, "role": u.role,
             "requests": u.requests, "failures": u.failures, "input_tokens": u.input_tokens,
             "output_tokens": u.output_tokens, "audio_seconds": round(u.audio_seconds, 1),
             "cost_usd": round(u.cost_usd, 4),
             "avg_latency_ms": int(u.latency_ms_total / u.requests) if u.requests else 0}
            for u in await c.usage.summary()]
