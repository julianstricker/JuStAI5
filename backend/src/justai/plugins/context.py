"""In-process implementation of the SDK :class:`PluginContext`.

Every registration is recorded with the plugin as owner, so disabling a plugin
removes exactly what it contributed. All capabilities are permission-checked.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from justai_sdk.events import Event, EventSource
from justai_sdk.manifest import PluginManifest
from justai_sdk.permissions import Permission
from justai_sdk.plugin import (
    CoreServices,
    DisplayComponentSpec,
    EventHandler,
    PermissionDenied,
    PluginContext,
    PluginStore,
)
from justai_sdk.tools import ToolDefinition, ToolHandler
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from justai.db.engine import Database
from justai.db.models import PluginDocument
from justai.events.bus import EventBus
from justai.events.catalog import EventTypeSpec
from justai.plugins.http import AllowlistHttp
from justai.plugins.providers import ProviderRegistry
from justai.tools.registry import ToolRegistry

_PROVIDER_PERMISSIONS = {
    "device_driver": Permission.DEVICES_PROVIDE,
    "discovery": Permission.NETWORK_DISCOVERY,
    "llm": Permission.AI_PROVIDE,
    "realtime": Permission.AI_PROVIDE,
    "stt": Permission.AI_PROVIDE,
    "tts": Permission.AI_PROVIDE,
    "embedding": Permission.AI_PROVIDE,
    "wakeword": Permission.AI_PROVIDE,
    "object_detector": Permission.AI_PROVIDE,
    "face_analyzer": Permission.AI_PROVIDE,
}


class DisplayComponentRegistry(Protocol):
    def register(self, spec: DisplayComponentSpec, owner: str) -> None: ...

    def unregister_owner(self, owner: str) -> None: ...


class ServicesBackend(Protocol):
    """Core operations behind :class:`CoreServices` (implemented by the container)."""

    async def list_devices(self) -> list[dict[str, Any]]: ...

    async def list_rooms(self) -> list[dict[str, Any]]: ...

    async def snapshot(self, device_id: str) -> bytes: ...

    async def memory_search(self, query: str, person_id: str | None, limit: int) -> list[dict[str, Any]]: ...

    async def say(self, room_id: str, text: str, plugin_id: str) -> None: ...

    async def show(self, room_id: str, document: dict[str, Any], plugin_id: str) -> str: ...

    async def complete(self, prompt: str, role: str) -> str: ...


class _Services(CoreServices):
    def __init__(self, ctx: InProcessPluginContext, backend: ServicesBackend) -> None:
        self._ctx = ctx
        self._backend = backend

    async def list_devices(self) -> list[dict[str, Any]]:
        self._ctx.require(Permission.DEVICES_READ)
        return await self._backend.list_devices()

    async def list_rooms(self) -> list[dict[str, Any]]:
        self._ctx.require(Permission.DEVICES_READ)
        return await self._backend.list_rooms()

    async def snapshot(self, device_id: str) -> bytes:
        self._ctx.require(Permission.CAMERA_READ)
        return await self._backend.snapshot(device_id)

    async def memory_search(self, query: str, *, person_id: str | None = None,
                            limit: int = 5) -> list[dict[str, Any]]:
        self._ctx.require(Permission.MEMORY_READ)
        return await self._backend.memory_search(query, person_id, limit)

    async def say(self, room_id: str, text: str) -> None:
        self._ctx.require(Permission.SPEAKER_WRITE)
        await self._backend.say(room_id, text, self._ctx.plugin_id)

    async def show(self, room_id: str, document: dict[str, Any]) -> str:
        self._ctx.require(Permission.DISPLAY_WRITE)
        return await self._backend.show(room_id, document, self._ctx.plugin_id)

    async def complete(self, prompt: str, *, role: str = "background") -> str:
        self._ctx.require(Permission.AI_INVOKE)
        return await self._backend.complete(prompt, role)


class DbPluginStore(PluginStore):
    def __init__(self, db: Database, plugin_id: str) -> None:
        self.db = db
        self.plugin_id = plugin_id

    async def get(self, key: str) -> Any | None:
        async with self.db.session() as s:
            row = await s.get(PluginDocument, (self.plugin_id, key))
        return row.value if row else None

    async def put(self, key: str, value: Any) -> None:
        async with self.db.session() as s:
            stmt = insert(PluginDocument).values(plugin_id=self.plugin_id, key=key, value=value)
            await s.execute(stmt.on_conflict_do_update(
                index_elements=[PluginDocument.plugin_id, PluginDocument.key], set_={"value": value}))

    async def delete(self, key: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(PluginDocument).where(PluginDocument.plugin_id == self.plugin_id,
                                                         PluginDocument.key == key))

    async def keys(self, prefix: str = "") -> list[str]:
        async with self.db.session() as s:
            rows = await s.scalars(select(PluginDocument.key).where(
                PluginDocument.plugin_id == self.plugin_id, PluginDocument.key.startswith(prefix)))
            return sorted(rows.all())


class InProcessPluginContext(PluginContext):
    def __init__(
        self,
        manifest: PluginManifest,
        config: dict[str, Any],
        granted: frozenset[str],
        *,
        db: Database,
        bus: EventBus,
        providers: ProviderRegistry,
        tools: ToolRegistry,
        components: DisplayComponentRegistry,
        backend: ServicesBackend,
        data_dir: Any = None,
    ) -> None:
        self.plugin_id = manifest.id
        self.manifest = manifest
        self.config = config
        self.permissions = granted
        self.data_dir = data_dir
        self.logger = logging.getLogger(f"plugin.{manifest.id}")
        self._db = db
        self._bus = bus
        self._providers = providers
        self._tools = tools
        self._components = components
        self._unsubscribers: list[Callable[[], None]] = []
        self._jobs: list[asyncio.Task[None]] = []
        self._http = AllowlistHttp(manifest.id, manifest.network_allowlist,
                                   allow_lan=Permission.NETWORK_LAN in granted)
        self._store = DbPluginStore(db, manifest.id)
        self._services = _Services(self, backend)

    # registration -------------------------------------------------------------
    def register_tool(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.require(Permission.TOOLS_PROVIDE)
        undeclared = set(definition.permissions) - set(self.manifest.permissions)
        if undeclared:
            raise PermissionDenied(sorted(undeclared)[0],
                                   "tools may only require permissions declared in the manifest")
        self._tools.register(definition, handler, owner=self.plugin_id)

    def register_provider(self, kind: str, provider: Any) -> None:
        needed = _PROVIDER_PERMISSIONS.get(kind)
        if needed is None:
            raise ValueError(f"unknown provider kind {kind}")
        self.require(needed)
        self._providers.register(kind, provider, self.plugin_id)

    def register_display_component(self, spec: DisplayComponentSpec) -> None:
        self.require(Permission.DISPLAY_WRITE)
        if not spec.type.startswith(f"{self.plugin_id}.") and not spec.type.startswith(self.plugin_id):
            spec = spec.model_copy(update={"type": f"{self.plugin_id}.{spec.type}"})
        self._components.register(spec, owner=self.plugin_id)

    def register_event_type(self, type: str, description: str, *, durable: bool = False) -> None:
        if not type.startswith(f"plugin.{self.plugin_id}."):
            type = f"plugin.{self.plugin_id}.{type}"
        self._bus.catalog.register(EventTypeSpec(type, description, durable=durable,
                                                 owner=f"plugin:{self.plugin_id}"))

    # background jobs ----------------------------------------------------------------
    def run_every(self, seconds: float, callback: Callable[[], Awaitable[None]], *,
                  name: str = "job") -> None:
        from justai_sdk.jobs import run_periodic

        self._jobs.append(asyncio.create_task(
            run_periodic(max(1.0, seconds), callback, self.logger, name),
            name=f"plugin-job:{self.plugin_id}:{name}"))

    # events ----------------------------------------------------------------------
    async def publish(self, event: Event) -> None:
        self.require(Permission.EVENTS_PUBLISH)
        source = event.source.model_copy(update={"kind": "plugin", "plugin_id": self.plugin_id})
        await self._bus.publish(event.model_copy(update={"source": source}))

    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        self.require(Permission.EVENTS_SUBSCRIBE)
        unsub = self._bus.subscribe(pattern, handler, name=f"plugin:{self.plugin_id}:{pattern}")
        self._unsubscribers.append(unsub)
        return unsub

    @property
    def http(self) -> AllowlistHttp:
        self.require(Permission.NETWORK_HTTP)
        return self._http

    @property
    def store(self) -> PluginStore:
        self.require(Permission.STORAGE_PLUGIN)
        return self._store

    @property
    def services(self) -> CoreServices:
        return self._services

    def source(self) -> EventSource:
        return EventSource(kind="plugin", plugin_id=self.plugin_id)

    async def release(self) -> None:
        """Remove everything this plugin registered."""
        for unsub in self._unsubscribers:
            unsub()
        self._unsubscribers.clear()
        for job in self._jobs:
            job.cancel()
        self._jobs.clear()
        self._tools.unregister_owner(self.plugin_id)
        self._providers.unregister_plugin(self.plugin_id)
        self._components.unregister_owner(self.plugin_id)
        self._bus.catalog.unregister_owner(f"plugin:{self.plugin_id}")
        await self._http.aclose()
