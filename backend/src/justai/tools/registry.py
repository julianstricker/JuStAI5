"""Central tool registry and the secure executor.

Every action of the assistant - whether triggered by the LLM, an automation, the
admin UI or a plugin - is a tool call executed here:

parameter validation -> permission check -> confirmation (if required) ->
timeout-guarded execution -> structured result -> audit log.
"""

from __future__ import annotations

import asyncio
import builtins
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from justai_sdk.events import Event, EventSource
from justai_sdk.ports.ai import ToolSpec
from justai_sdk.tools import ToolContext, ToolDefinition, ToolHandler, ToolResult
from pydantic import ValidationError

from justai.common.redact import redact
from justai.db.engine import Database
from justai.db.models import ToolExecution
from justai.events.bus import EventBus
from justai.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class RegisteredTool:
    definition: ToolDefinition
    handler: ToolHandler
    owner: str  # "core" or plugin id


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler, owner: str = "core") -> None:
        existing = self._tools.get(definition.name)
        if existing and existing.owner != owner:
            raise ValueError(f"tool {definition.name} already registered by {existing.owner}")
        if owner != "core":
            definition = definition.model_copy(update={"plugin_id": owner})
        self._tools[definition.name] = RegisteredTool(definition, handler, owner)

    def unregister_owner(self, owner: str) -> builtins.list[str]:
        names = [n for n, t in self._tools.items() if t.owner == owner]
        for n in names:
            del self._tools[n]
        return names

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name) or self._tools.get(name.replace("__", "."))

    def list(self) -> builtins.list[RegisteredTool]:
        return sorted(self._tools.values(), key=lambda t: t.definition.name)

    def available(self, permissions: frozenset[str], *, conversation: bool = True) -> builtins.list[RegisteredTool]:
        return [
            t for t in self.list()
            if set(t.definition.permissions) <= permissions
            and (t.definition.available_in_conversation or not conversation)
        ]

    def specs(self, permissions: frozenset[str]) -> builtins.list[ToolSpec]:
        return [
            ToolSpec(name=t.definition.llm_name, description=t.definition.description,
                     parameters=t.definition.parameters_schema())
            for t in self.available(permissions)
        ]


@dataclass
class PendingConfirmation:
    token: str
    tool: str
    args: dict[str, Any]
    context: ToolContext
    created: float
    user_turn: int
    description: str


TurnCounter = Callable[[str], int]


class ConfirmationManager:
    """Deterministic confirmation for critical tools.

    The LLM cannot confirm on its own behalf: a confirmation is only accepted if the
    user produced a new utterance after the confirmation was requested.
    """

    TTL_S = 120.0

    def __init__(self, turn_counter: TurnCounter) -> None:
        self._pending: dict[str, PendingConfirmation] = {}
        self._turn_counter = turn_counter

    def create(self, tool: str, args: dict[str, Any], ctx: ToolContext, description: str) -> str:
        self._gc()
        token = secrets.token_hex(4)
        turn = self._turn_counter(ctx.session_id) if ctx.session_id else 0
        self._pending[token] = PendingConfirmation(token, tool, args, ctx, time.monotonic(), turn,
                                                   description)
        return token

    def take(self, token: str, ctx: ToolContext) -> PendingConfirmation:
        self._gc()
        pending = self._pending.get(token)
        if pending is None:
            raise LookupError("unknown or expired confirmation")
        if pending.context.session_id != ctx.session_id:
            raise PermissionError("confirmation belongs to another session")
        if ctx.session_id and self._turn_counter(ctx.session_id) <= pending.user_turn:
            raise PermissionError("the user has not answered yet; ask the user first")
        del self._pending[token]
        return pending

    def cancel(self, token: str) -> None:
        self._pending.pop(token, None)

    def _gc(self) -> None:
        now = time.monotonic()
        for k in [k for k, p in self._pending.items() if now - p.created > self.TTL_S]:
            del self._pending[k]


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, bus: EventBus, db: Database | None,
                 confirmations: ConfirmationManager) -> None:
        self.registry = registry
        self.bus = bus
        self.db = db
        self.confirmations = confirmations
        self._listeners: list[Callable[[str, ToolContext, ToolResult], Awaitable[None]]] = []

    async def execute(self, name: str, args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        started = time.monotonic()
        tool = self.registry.get(name)
        if tool is None:
            result = ToolResult.failure("unknown_tool", f"Tool {name} gibt es nicht.")
            await self._record(name, None, args, ctx, result, started)
            return result
        definition = tool.definition
        missing = sorted(set(definition.permissions) - ctx.permissions)
        if missing:
            result = ToolResult.failure("permission_denied",
                                        f"Keine Berechtigung für {definition.name}: {missing}")
            await self._record(definition.name, tool.owner, args, ctx, result, started, "denied")
            return result
        try:
            params = definition.parameters.model_validate(args)
        except ValidationError as exc:
            errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
            result = ToolResult.failure("invalid_arguments", "Ungültige Parameter", data=errors)
            await self._record(definition.name, tool.owner, args, ctx, result, started)
            return result
        if definition.requires_confirmation and not ctx.confirmed:
            description = f"{definition.name}({redact(args)})"
            token = self.confirmations.create(definition.name, args, ctx, description)
            result = ToolResult(
                ok=False, needs_confirmation=True, confirmation_token=token,
                error_code="confirmation_required",
                message=("Diese Aktion muss der Benutzer bestätigen. Frage ihn ausdrücklich und "
                         "rufe nach seiner Zustimmung assistant.confirm_action mit dem Token auf."),
            )
            await self._record(definition.name, tool.owner, args, ctx, result, started,
                               "needs_confirmation")
            return result
        try:
            result = await asyncio.wait_for(tool.handler(params, ctx), timeout=definition.timeout_s)
            if not isinstance(result, ToolResult):
                result = ToolResult.success(result)
        except TimeoutError:
            result = ToolResult.failure("timeout", f"{definition.name} hat zu lange gedauert")
        except PermissionError as exc:
            result = ToolResult.failure("permission_denied", str(exc))
        except Exception as exc:
            code = getattr(exc, "code", "tool_error")
            log.warning("tool failed", tool=definition.name, error=str(exc), exc_info=True)
            message = getattr(exc, "message", None) or str(exc)
            problems = (getattr(exc, "details", None) or {}).get("errors")
            if problems:  # let the model correct its arguments
                message += ": " + "; ".join(
                    f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg')}" for e in problems[:6])
            result = ToolResult.failure(str(code), message)
        await self._record(definition.name, tool.owner, args, ctx, result, started)
        for listener in self._listeners:
            await listener(definition.name, ctx, result)
        return result

    async def confirm(self, token: str, ctx: ToolContext) -> ToolResult:
        try:
            pending = self.confirmations.take(token, ctx)
        except (LookupError, PermissionError) as exc:
            return ToolResult.failure("confirmation_invalid", str(exc))
        confirmed_ctx = pending.context.model_copy(update={"confirmed": True})
        return await self.execute(pending.tool, pending.args, confirmed_ctx)

    def on_executed(self, listener: Callable[[str, ToolContext, ToolResult], Awaitable[None]]) -> None:
        self._listeners.append(listener)

    async def _record(self, name: str, owner: str | None, args: dict[str, Any], ctx: ToolContext,
                      result: ToolResult, started: float, status: str | None = None) -> None:
        duration_ms = int((time.monotonic() - started) * 1000)
        status = status or ("ok" if result.ok else ("timeout" if result.error_code == "timeout"
                                                   else "error"))
        if self.db is not None:
            try:
                async with self.db.session() as s:
                    s.add(ToolExecution(
                        tool=name, plugin_id=None if owner == "core" else owner,
                        origin=ctx.origin, session_id=ctx.session_id, room_id=ctx.room_id,
                        actor=ctx.user_id or ctx.person_id or ctx.automation_id,
                        params=redact(args), status=status,
                        result=redact({"message": result.message, "error_code": result.error_code}),
                        error=None if result.ok else result.message, duration_ms=duration_ms,
                    ))
            except Exception as exc:
                log.warning("tool execution log failed", error=str(exc))
        await self.bus.publish(Event(
            type="tool.executed",
            source=EventSource(kind="tool", session_id=ctx.session_id, room_id=ctx.room_id),
            payload={"tool": name, "status": status, "duration_ms": duration_ms,
                     "origin": str(ctx.origin)},
            correlation_id=ctx.correlation_id,
        ))
