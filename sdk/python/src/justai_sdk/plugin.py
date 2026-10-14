"""Plugin base class and the context API a plugin may use.

A plugin never imports core modules. Everything it can do goes through the
:class:`PluginContext`, whose methods check the permissions granted to the plugin.
For sandboxed plugins the same API is implemented as an RPC proxy, and the
permission checks happen inside the core.
"""

from __future__ import annotations

import abc
import logging
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from justai_sdk.events import Event
from justai_sdk.tools import ToolDefinition, ToolHandler


class PluginError(Exception):
    """Base class for errors raised by plugins."""


class PermissionDenied(PluginError):
    def __init__(self, permission: str, detail: str = "") -> None:
        super().__init__(f"permission denied: {permission}{' (' + detail + ')' if detail else ''}")
        self.permission = permission


class HealthState(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    FAILED = "failed"


class PluginHealth(BaseModel):
    state: HealthState = HealthState.OK
    detail: str | None = None
    metrics: dict[str, float] = Field(default_factory=dict)


class DisplayComponentSpec(BaseModel):
    """A display component contributed by a plugin.

    ``template`` composes built-in primitive components (safe for any plugin).
    ``props_schema`` validates the props the assistant may pass.
    """

    type: str = Field(pattern=r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*)*$")
    description: str
    props_schema: dict[str, Any]
    template: dict[str, Any]


EventHandler = Callable[[Event], Awaitable[None]]


class HttpResponse(BaseModel):
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    text: str = ""

    def json(self) -> Any:
        import json

        return json.loads(self.text)


class PluginHttp(abc.ABC):
    """HTTP client restricted to the plugin's ``network_allowlist``."""

    @abc.abstractmethod
    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 10.0,
    ) -> HttpResponse: ...

    async def get(self, url: str, **kw: Any) -> HttpResponse:
        return await self.request("GET", url, **kw)

    async def post(self, url: str, **kw: Any) -> HttpResponse:
        return await self.request("POST", url, **kw)


class PluginStore(abc.ABC):
    """Small JSON document store, isolated per plugin."""

    @abc.abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abc.abstractmethod
    async def put(self, key: str, value: Any) -> None: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def keys(self, prefix: str = "") -> list[str]: ...


class CoreServices(abc.ABC):
    """Capability-gated access to core functionality."""

    @abc.abstractmethod
    async def list_devices(self) -> list[dict[str, Any]]: ...  # devices.read

    @abc.abstractmethod
    async def list_rooms(self) -> list[dict[str, Any]]: ...  # devices.read

    @abc.abstractmethod
    async def snapshot(self, device_id: str) -> bytes: ...  # camera.read

    @abc.abstractmethod
    async def memory_search(
        self, query: str, *, person_id: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]: ...  # memory.read

    @abc.abstractmethod
    async def say(self, room_id: str, text: str) -> None: ...  # speaker.write

    @abc.abstractmethod
    async def show(self, room_id: str, document: dict[str, Any]) -> str: ...  # display.write

    @abc.abstractmethod
    async def complete(self, prompt: str, *, role: str = "background") -> str: ...  # ai.invoke


class PluginContext(abc.ABC):
    plugin_id: str
    config: dict[str, Any]
    permissions: frozenset[str]
    logger: logging.Logger | logging.LoggerAdapter[logging.Logger]

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise PermissionDenied(permission, f"plugin {self.plugin_id}")

    # -- registration ----------------------------------------------------------------
    @abc.abstractmethod
    def register_tool(self, definition: ToolDefinition, handler: ToolHandler) -> None: ...

    @abc.abstractmethod
    def register_provider(self, kind: str, provider: Any) -> None:
        """Register a port implementation.

        ``kind`` is one of: device_driver, discovery, llm, realtime, stt, tts, embedding,
        wakeword, object_detector, face_analyzer.
        """

    @abc.abstractmethod
    def register_display_component(self, spec: DisplayComponentSpec) -> None: ...

    @abc.abstractmethod
    def register_event_type(self, type: str, description: str, *, durable: bool = False) -> None: ...

    # -- events --------------------------------------------------------------------
    @abc.abstractmethod
    async def publish(self, event: Event) -> None: ...

    @abc.abstractmethod
    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]: ...

    # -- services ------------------------------------------------------------------
    @property
    @abc.abstractmethod
    def http(self) -> PluginHttp: ...

    @property
    @abc.abstractmethod
    def store(self) -> PluginStore: ...

    @property
    @abc.abstractmethod
    def services(self) -> CoreServices: ...


class Plugin:
    """Base class for all plugins. Override the lifecycle hooks you need."""

    def __init__(self, ctx: PluginContext) -> None:
        self.ctx = ctx

    async def setup(self) -> None:
        """Register tools/providers. Called once after the plugin is loaded."""

    async def start(self) -> None:
        """Start background work. Called after all plugins are set up."""

    async def stop(self) -> None:
        """Release resources. Must be idempotent."""

    async def health(self) -> PluginHealth:
        return PluginHealth()

    async def on_config_changed(self, config: dict[str, Any]) -> bool:
        """Apply new configuration. Return False to request a restart instead."""
        return False
