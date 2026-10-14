"""Tool definitions: the single mechanism through which the assistant acts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SideEffect(StrEnum):
    NONE = "none"  # pure computation
    READ = "read"  # reads state or sensors
    WRITE = "write"  # changes stored state (memory, automations, ...)
    PHYSICAL = "physical"  # acts on the physical world (PTZ, speakers, displays)


class InvocationOrigin(StrEnum):
    CONVERSATION = "conversation"
    AUTOMATION = "automation"
    ADMIN = "admin"
    PLUGIN = "plugin"
    SYSTEM = "system"


class ToolContext(BaseModel):
    """Who calls a tool, from where. Built by the core, never by the LLM."""

    model_config = ConfigDict(frozen=True)

    call_id: str
    origin: InvocationOrigin
    session_id: str | None = None
    endpoint_id: str | None = None
    room_id: str | None = None
    user_id: str | None = None  # authenticated admin user (admin UI)
    person_id: str | None = None  # recognised/declared speaker (conversation)
    roles: frozenset[str] = frozenset()
    permissions: frozenset[str] = frozenset()
    language: str | None = None
    correlation_id: str | None = None
    confirmed: bool = False
    automation_id: str | None = None


class ToolResult(BaseModel):
    ok: bool = True
    data: Any = None
    message: str | None = None  # short natural-language summary for the model
    error_code: str | None = None
    needs_confirmation: bool = False
    confirmation_token: str | None = None

    @classmethod
    def success(cls, data: Any = None, message: str | None = None) -> ToolResult:
        return cls(ok=True, data=data, message=message)

    @classmethod
    def failure(cls, error_code: str, message: str, data: Any = None) -> ToolResult:
        return cls(ok=False, error_code=error_code, message=message, data=data)


class ToolDefinition(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
    description: str
    parameters: type[BaseModel]
    category: str = "general"
    permissions: list[str] = Field(default_factory=list)
    side_effect: SideEffect = SideEffect.READ
    requires_confirmation: bool = False
    timeout_s: float = 15.0
    available_in_conversation: bool = True
    plugin_id: str | None = None

    def parameters_schema(self) -> dict[str, Any]:
        schema = self.parameters.model_json_schema()
        schema.pop("title", None)
        return schema

    @property
    def llm_name(self) -> str:
        """Function name safe for all LLM providers (dots are not universally allowed)."""
        return self.name.replace(".", "__")


ToolHandler = Callable[[Any, ToolContext], Awaitable[ToolResult]]


class NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
