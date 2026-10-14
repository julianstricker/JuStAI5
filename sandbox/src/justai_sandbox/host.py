"""Plugin host process: runs ONE untrusted plugin, talks JSON-RPC over stdin/stdout.

Every capability the plugin uses (HTTP, storage, core services, events) is an RPC
"upcall" that the sandbox server forwards to the core gateway, where permissions,
the HTTP allowlist and SSRF protection are enforced. The plugin never gets direct
network access (the sandbox container is on an internal network).
"""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from justai_sdk.events import Event
from justai_sdk.manifest import PluginManifest
from justai_sdk.plugin import (
    CoreServices,
    DisplayComponentSpec,
    EventHandler,
    HttpResponse,
    Plugin,
    PluginContext,
    PluginHttp,
    PluginStore,
)
from justai_sdk.tools import ToolContext, ToolDefinition, ToolHandler, ToolResult

from justai_sandbox.rpc import RpcPeer


class _StdoutWriter:
    def write(self, data: bytes) -> None:
        sys.stdout.buffer.write(data)

    async def drain(self) -> None:
        sys.stdout.buffer.flush()


class ProxyHttp(PluginHttp):
    def __init__(self, peer: RpcPeer) -> None:
        self.peer = peer

    async def request(self, method: str, url: str, *, params: dict[str, Any] | None = None,
                      json: Any = None, headers: dict[str, str] | None = None,
                      timeout_s: float = 10.0) -> HttpResponse:
        result = await self.peer.call("gateway", {"op": "http", "args": {
            "method": method, "url": url, "params": params, "json": json, "headers": headers,
            "timeout_s": timeout_s}}, timeout=timeout_s + 5)
        return HttpResponse.model_validate(result)


class ProxyStore(PluginStore):
    def __init__(self, peer: RpcPeer) -> None:
        self.peer = peer

    async def _op(self, op: str, **args: Any) -> Any:
        return await self.peer.call("gateway", {"op": f"store.{op}", "args": args})

    async def get(self, key: str) -> Any | None:
        return await self._op("get", key=key)

    async def put(self, key: str, value: Any) -> None:
        await self._op("put", key=key, value=value)

    async def delete(self, key: str) -> None:
        await self._op("delete", key=key)

    async def keys(self, prefix: str = "") -> list[str]:
        return list(await self._op("keys", prefix=prefix))


class ProxyServices(CoreServices):
    def __init__(self, peer: RpcPeer) -> None:
        self.peer = peer

    async def _op(self, op: str, **args: Any) -> Any:
        return await self.peer.call("gateway", {"op": f"services.{op}", "args": args})

    async def list_devices(self) -> list[dict[str, Any]]:
        return list(await self._op("list_devices"))

    async def list_rooms(self) -> list[dict[str, Any]]:
        return list(await self._op("list_rooms"))

    async def snapshot(self, device_id: str) -> bytes:
        return base64.b64decode(await self._op("snapshot", device_id=device_id))

    async def memory_search(self, query: str, *, person_id: str | None = None,
                            limit: int = 5) -> list[dict[str, Any]]:
        return list(await self._op("memory_search", query=query, person_id=person_id, limit=limit))

    async def say(self, room_id: str, text: str) -> None:
        await self._op("say", room_id=room_id, text=text)

    async def show(self, room_id: str, document: dict[str, Any]) -> str:
        return str(await self._op("show", room_id=room_id, document=document))

    async def complete(self, prompt: str, *, role: str = "background") -> str:
        return str(await self._op("complete", prompt=prompt, role=role))


class SandboxContext(PluginContext):
    def __init__(self, manifest: PluginManifest, config: dict[str, Any], permissions: list[str],
                 peer: RpcPeer) -> None:
        self.plugin_id = manifest.id
        self.manifest = manifest
        self.config = config
        self.permissions = frozenset(permissions)
        self.logger = logging.getLogger(f"plugin.{manifest.id}")
        self.peer = peer
        self.tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
        self.components: list[DisplayComponentSpec] = []
        self._http = ProxyHttp(peer)
        self._store = ProxyStore(peer)
        self._services = ProxyServices(peer)

    def register_tool(self, definition: ToolDefinition, handler: ToolHandler) -> None:
        self.require("tools.provide")
        self.tools[definition.name] = (definition, handler)

    def register_provider(self, kind: str, provider: Any) -> None:
        raise PermissionError("sandboxed plugins cannot provide drivers or AI providers")

    def register_display_component(self, spec: DisplayComponentSpec) -> None:
        self.require("display.write")
        self.components.append(spec)

    def register_event_type(self, type: str, description: str, *, durable: bool = False) -> None:
        return None

    async def publish(self, event: Event) -> None:
        self.require("events.publish")
        await self.peer.call("gateway", {"op": "events.publish", "args": {"event": event.model_dump(mode="json")}})

    def subscribe(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        raise PermissionError("event subscriptions are not available in the sandbox")

    @property
    def http(self) -> PluginHttp:
        self.require("network.http")
        return self._http

    @property
    def store(self) -> PluginStore:
        self.require("storage.plugin")
        return self._store

    @property
    def services(self) -> CoreServices:
        return self._services


async def main(plugin_dir: str) -> None:
    root = Path(plugin_dir)
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    state: dict[str, Any] = {}

    async def handle(method: str, params: dict[str, Any]) -> Any:
        if method == "start":
            manifest = PluginManifest.model_validate(params["manifest"])
            ctx = SandboxContext(manifest, params.get("config") or {}, params.get("permissions") or [], peer)
            module_path, class_name = manifest.entrypoint.split(":", 1)
            spec = importlib.util.spec_from_file_location(
                "sandboxed_plugin", root / "__init__.py", submodule_search_locations=[str(root)])
            assert spec and spec.loader
            package = importlib.util.module_from_spec(spec)
            sys.modules["sandboxed_plugin"] = package
            if (root / "__init__.py").exists():
                spec.loader.exec_module(package)
            module = importlib.import_module(f"sandboxed_plugin.{module_path}")
            plugin: Plugin = getattr(module, class_name)(ctx)
            await plugin.setup()
            await plugin.start()
            state.update(plugin=plugin, ctx=ctx)
            return {"tools": [{
                "name": d.name, "description": d.description, "parameters": d.parameters_schema(),
                "permissions": d.permissions, "side_effect": d.side_effect.value,
                "requires_confirmation": d.requires_confirmation, "timeout_s": d.timeout_s,
                "category": d.category} for d, _ in ctx.tools.values()],
                "components": [c.model_dump() for c in ctx.components]}
        if method == "tool":
            ctx = state["ctx"]
            definition, handler = ctx.tools[params["name"]]
            args = definition.parameters.model_validate(params.get("args") or {})
            tctx = ToolContext.model_validate(params["context"])
            result = await handler(args, tctx)
            if not isinstance(result, ToolResult):
                result = ToolResult.success(result)
            return json.loads(result.model_dump_json())
        if method == "health":
            plugin = state.get("plugin")
            return (await plugin.health()).model_dump() if plugin else {"state": "failed"}
        if method == "stop":
            plugin = state.get("plugin")
            if plugin:
                await plugin.stop()
            loop.call_later(0.1, sys.exit, 0)
            return True
        raise ValueError(f"unknown method {method}")

    peer = RpcPeer(reader, _StdoutWriter(), handle)
    peer.start()
    await peer.wait_closed()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    asyncio.run(main(sys.argv[1]))
