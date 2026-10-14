"""Memory feature: tools for the assistant, background jobs."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from justai_sdk.permissions import Permission
from justai_sdk.tools import SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, Field

from justai.memory.service import MemoryIn, MemoryService, Provenance

if TYPE_CHECKING:
    from justai.container import Container
    from justai.tools.registry import ToolRegistry


class SearchParams(BaseModel):
    query: str = Field(description="Wonach im Gedächtnis gesucht werden soll")


class RememberParams(BaseModel):
    content: str = Field(description="Die Information als vollständiger Satz, z. B. 'Julian hat einen weißen XPENG bestellt'")
    kind: str = Field("fact", description="fact | preference | episode | procedure")
    private: bool = Field(False, description="Nur für die sprechende Person sichtbar")
    subject: str | None = Field(None, description="Worum es geht, z. B. 'Julian'")
    predicate: str | None = Field(None, description="Beziehung in snake_case, z. B. 'ordered_vehicle'")
    user_requested: bool = Field(False, description="True, wenn der Benutzer ausdrücklich 'merk dir' o. ä. gesagt hat")


class ForgetSearch(BaseModel):
    query: str = Field(description="Was vergessen werden soll, z. B. 'Auto von gestern'")


class ForgetParams(BaseModel):
    memory_ids: list[str] = Field(min_length=1, max_length=20)


class MemoryExtension:
    def __init__(self, c: Container, service: MemoryService) -> None:
        self.c = c
        self.service = service
        self._task: asyncio.Task[None] | None = None

    # delegate for the conversation layer
    async def recall(self, query: str, *, person_id: str | None, room_id: str | None,
                     limit: int = 6) -> list[str]:
        return await self.service.recall(query, person_id=person_id, room_id=room_id, limit=limit)

    async def search(self, query: str, **kw: Any) -> Any:
        return await self.service.search(query, **kw)

    async def start(self) -> None:
        async def extract(payload: dict[str, Any]) -> None:
            await self.service.extract_from_session(payload["session_id"])

        async def consolidate(_: dict[str, Any]) -> None:
            await self.service.consolidate()

        self.c.jobs.register("memory.extract", extract)
        self.c.jobs.register("memory.consolidate", consolidate)
        self._task = asyncio.create_task(self._daily(), name="memory-consolidation")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    async def _daily(self) -> None:
        while True:
            await asyncio.sleep(24 * 3600)
            with contextlib.suppress(Exception):
                await self.c.jobs.enqueue("memory.consolidate", {}, dedup_key="memory.consolidate")

    def register_tools(self, reg: ToolRegistry) -> None:
        svc = self.service

        async def search(p: SearchParams, ctx: ToolContext) -> ToolResult:
            hits = await svc.search(p.query, person_id=ctx.person_id, room_id=ctx.room_id, limit=8)
            return ToolResult.success([{"id": h.id, "content": h.content, "provenance": h.provenance,
                                        "confidence": round(h.confidence, 2),
                                        "updated": h.updated_at.date().isoformat()} for h in hits],
                                      message=f"{len(hits)} Erinnerungen gefunden")

        reg.register(ToolDefinition(
            name="memory.search",
            description="Durchsucht das Langzeitgedächtnis (frühere Gespräche, Fakten über Personen, "
                        "Vorlieben). Ergebnisse mit Herkunft; 'inferred' sind nur Vermutungen.",
            parameters=SearchParams, category="memory", permissions=[Permission.MEMORY_READ]), search)

        async def remember(p: RememberParams, ctx: ToolContext) -> ToolResult:
            owner = ctx.person_id
            hit = await svc.add(MemoryIn(
                content=p.content, kind=p.kind, scope="private" if p.private and owner else "shared",
                owner_person_id=owner, room_id=ctx.room_id, subject=p.subject, predicate=p.predicate,
                provenance=Provenance.CONFIRMED if p.user_requested else Provenance.EXTRACTED,
                confidence=0.95 if p.user_requested else 0.8,
                source={"type": "conversation", "session_id": ctx.session_id, "tool": True}))
            return ToolResult.success({"id": hit.id}, message="Gemerkt")

        reg.register(ToolDefinition(
            name="memory.remember", description="Speichert eine wichtige Information dauerhaft.",
            parameters=RememberParams, category="memory", permissions=[Permission.MEMORY_WRITE],
            side_effect=SideEffect.WRITE), remember)

        async def find_forget(p: ForgetSearch, ctx: ToolContext) -> ToolResult:
            hits = await svc.search(p.query, person_id=ctx.person_id, room_id=ctx.room_id, limit=10)
            # Only the speaker's own or shared memories may be forgotten by voice.
            hits = [h for h in hits if h.owner_person_id in (None, ctx.person_id)]
            return ToolResult.success([{"id": h.id, "content": h.content,
                                        "updated": h.updated_at.date().isoformat()} for h in hits],
                                      message="Nenne dem Benutzer die Treffer und frage, welche gelöscht "
                                              "werden sollen; dann memory.forget mit den IDs.")

        reg.register(ToolDefinition(
            name="memory.find_to_forget",
            description="Sucht Erinnerungen, die der Benutzer vergessen lassen möchte (löscht nichts).",
            parameters=ForgetSearch, category="memory", permissions=[Permission.MEMORY_READ]), find_forget)

        async def forget(p: ForgetParams, ctx: ToolContext) -> ToolResult:
            deleted = 0
            for mid in p.memory_ids:
                hit = await svc.get(mid)
                if hit.owner_person_id not in (None, ctx.person_id):
                    continue
                await svc.delete(mid)
                deleted += 1
            await self.c.audit.record("assistant", "memory.forget", None, count=deleted,
                                      session=ctx.session_id)
            return ToolResult.success({"deleted": deleted}, message=f"{deleted} Erinnerungen gelöscht")

        reg.register(ToolDefinition(
            name="memory.forget", description="Löscht Erinnerungen endgültig (nach Bestätigung).",
            parameters=ForgetParams, category="memory", permissions=[Permission.MEMORY_WRITE],
            side_effect=SideEffect.WRITE, requires_confirmation=True), forget)
