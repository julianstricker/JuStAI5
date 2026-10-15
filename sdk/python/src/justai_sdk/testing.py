"""Test helpers for plugin authors: an in-memory :class:`PluginContext`."""

from __future__ import annotations

import fnmatch
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from justai_sdk.events import Event
from justai_sdk.manifest import PluginManifest, load_manifest
from justai_sdk.permissions import Permission
from justai_sdk.plugin import (
    CoreServices,
    DisplayComponentSpec,
    EventHandler,
    HttpResponse,
    PermissionDenied,
    PluginContext,
    PluginHttp,
    PluginStore,
)
from justai_sdk.tools import InvocationOrigin, ToolContext, ToolDefinition, ToolHandler, ToolResult

FakeRoute = Callable[[str, str, dict[str, Any] | None, Any], HttpResponse]


__all__ = ["FakeHttp", "FakePluginContext", "FakeServices", "MemoryStore", "load_manifest"]


class FakeHttp(PluginHttp):
    def __init__(self, allowlist: list[str], routes: dict[str, FakeRoute] | None = None) -> None:
        self.allowlist = allowlist
        self.routes = routes or {}
        self.requests: list[tuple[str, str]] = []

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        timeout_s: float = 10.0,
    ) -> HttpResponse:
        host = urlparse(url).hostname or ""
        if host not in self.allowlist:
            raise PermissionDenied("network.http", f"host {host} not in allowlist")
        self.requests.append((method, url))
        for pattern, route in self.routes.items():
            if fnmatch.fnmatch(url, pattern):
                return route(method, url, params, json)
        return HttpResponse(status=404, text="no fake route")


class MemoryStore(PluginStore):
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    async def get(self, key: str) -> Any | None:
        return self.data.get(key)

    async def put(self, key: str, value: Any) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)

    async def keys(self, prefix: str = "") -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))


class FakeServices(CoreServices):
    def __init__(self, ctx: FakePluginContext) -> None:
        self._ctx = ctx
        self.said: list[tuple[str, str]] = []
        self.shown: list[tuple[str, dict[str, Any]]] = []

    async def list_devices(self) -> list[dict[str, Any]]:
        self._ctx.require(Permission.DEVICES_READ)
        return []

    async def list_rooms(self) -> list[dict[str, Any]]:
        self._ctx.require(Permission.DEVICES_READ)
        return []

    async def snapshot(self, device_id: str) -> bytes:
        self._ctx.require(Permission.CAMERA_READ)
        return b""

    async def memory_search(
        self, query: str, *, person_id: str | None = None, limit: int = 5
    ) -> list[dict[str, Any]]:
        self._ctx.require(Permission.MEMORY_READ)
        return []

    async def say(self, room_id: str, text: str) -> None:
        self._ctx.require(Permission.SPEAKER_WRITE)
        self.said.append((room_id, text))

    async def show(self, room_id: str, document: dict[str, Any]) -> str:
        self._ctx.require(Permission.DISPLAY_WRITE)
        self.shown.append((room_id, document))
        return f"presentation-{len(self.shown)}"

    async def complete(self, prompt: str, *, role: str = "background") -> str:
        self._ctx.require(Permission.AI_INVOKE)
        return ""


class FakePluginContext(PluginContext):
    def __init__(
        self,
        manifest: PluginManifest | dict[str, Any],
        config: dict[str, Any] | None = None,
        *,
        http_routes: dict[str, FakeRoute] | None = None,
    ) -> None:
        if isinstance(manifest, dict):
            manifest = PluginManifest.model_validate(manifest)
        self.plugin_id = manifest.id
        self.manifest = manifest
        self.config = config or {}
        self.permissions = frozenset(manifest.permissions)
        self.logger = logging.getLogger(f"plugin.{manifest.id}")
        self.tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        self.providers: list[tuple[str, Any]] = []
        self.components: list[DisplayComponentSpec] = []
        self.events: list[Event] = []
        self.subscriptions: list[tuple[str, EventHandler]] = []
        self._http = FakeHttp(manifest.network_allowlist, http_routes)
        self._store = MemoryStore()
        self._services = FakeServices(self)

    def register_tool(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.require(Permission.TOOLS_PROVIDE)
        self.tools[definition.name] = (definition, handler)

    def register_provider(self, kind: str, provider: Any) -> None:
        self.providers.append((kind, provider))

    def register_display_component(self, spec: DisplayComponentSpec) -> None:
        self.components.append(spec)

    def register_event_type(self, type: str, description: str, *, durable: bool = False) -> None:
        return None

    async def publish(self, event: Event) -> None:
        self.require(Permission.EVENTS_PUBLISH)
        self.events.append(event)

    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        self.require(Permission.EVENTS_SUBSCRIBE)
        entry = (pattern, handler)
        self.subscriptions.append(entry)
        return lambda: self.subscriptions.remove(entry)

    @property
    def http(self) -> FakeHttp:
        self.require(Permission.NETWORK_HTTP)
        return self._http

    @property
    def store(self) -> MemoryStore:
        self.require(Permission.STORAGE_PLUGIN)
        return self._store

    @property
    def services(self) -> FakeServices:
        return self._services

    async def call_tool(self, name: str, params: dict[str, Any], **ctx_kw: Any) -> ToolResult:
        definition, handler = self.tools[name]
        parsed = definition.parameters.model_validate(params)
        ctx = ToolContext(call_id="test", origin=InvocationOrigin.CONVERSATION, **ctx_kw)
        return await handler(parsed, ctx)
