"""Core side of the sandbox: starts untrusted plugins remotely and proxies their tools."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import jsonschema
from justai_sdk.manifest import PluginManifest
from justai_sdk.plugin import DisplayComponentSpec, HealthState, PluginHealth
from justai_sdk.tools import SideEffect, ToolContext, ToolDefinition, ToolResult
from pydantic import BaseModel, ConfigDict

from justai.common.errors import Unavailable
from justai.events.catalog import EventTypeSpec
from justai.logging import get_logger

if TYPE_CHECKING:
    from justai.container import Container

log = get_logger(__name__)
MAX_PLUGIN_BYTES = 2_000_000


class _AnyArgs(BaseModel):
    """Arguments of a sandboxed tool; validated by JSON schema in the core and by
    pydantic inside the sandbox."""

    model_config = ConfigDict(extra="allow")


def _read_plugin_files(path: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    total = 0
    for f in sorted(path.rglob("*")):
        if f.is_dir() or "__pycache__" in f.parts or f.suffix in (".pyc",):
            continue
        rel = f.relative_to(path).as_posix()
        if f.suffix not in (".py", ".yaml", ".yml", ".json", ".txt", ".md"):
            continue
        content = f.read_text(encoding="utf-8")
        total += len(content)
        if total > MAX_PLUGIN_BYTES:
            raise ValueError("plugin too large for the sandbox")
        files[rel] = content
    return files


class SandboxClient:
    def __init__(self, c: Container, url: str, token: str) -> None:
        self.c = c
        self.url = url.rstrip("/")
        self.token = token
        self.granted: dict[str, frozenset[str]] = {}
        self.manifests: dict[str, PluginManifest] = {}
        self._http = httpx.AsyncClient(base_url=self.url, timeout=90,
                                       headers={"x-sandbox-token": token})

    async def available(self) -> bool:
        try:
            r = await self._http.get("/health", timeout=3)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def start_plugin(self, manifest: PluginManifest, path: Path, config: dict[str, Any],
                           granted: frozenset[str]) -> None:
        if not await self.available():
            raise Unavailable("sandbox service not reachable")
        gateway_token = self.c.auth.issue_scoped_token(manifest.id, "plugin-gateway", timedelta(days=3650))
        r = await self._http.post("/plugins/start", json={
            "plugin_id": manifest.id, "manifest": manifest.model_dump(mode="json"),
            "files": _read_plugin_files(path), "config": config, "permissions": sorted(granted),
            "gateway_token": gateway_token, "memory_mb": manifest.requirements.memory_mb})
        data = r.json()
        if r.status_code >= 400:
            raise RuntimeError(data.get("error", r.text))
        self.granted[manifest.id] = granted
        self.manifests[manifest.id] = manifest
        for spec in data.get("tools", []):
            self._register_proxy_tool(manifest, spec, granted)
        for comp in data.get("components", []):
            self.c.components.register(DisplayComponentSpec.model_validate(comp), owner=manifest.id)
        for ev in data.get("events", []):
            if str(ev.get("type", "")).startswith(f"plugin.{manifest.id}."):
                self.c.bus.catalog.register(EventTypeSpec(
                    str(ev["type"]), str(ev.get("description", ""))[:300], durable=bool(ev.get("durable")),
                    owner=f"plugin:{manifest.id}"))

    def _register_proxy_tool(self, manifest: PluginManifest, spec: dict[str, Any], granted: frozenset[str]) -> None:
        schema = spec.get("parameters") or {"type": "object"}
        jsonschema.Draft202012Validator.check_schema(schema)
        undeclared = set(spec.get("permissions") or []) - granted
        if undeclared:
            raise PermissionError(f"tool {spec['name']} needs ungranted permissions {sorted(undeclared)}")

        class Params(_AnyArgs):
            @classmethod
            def model_json_schema(cls, *a: Any, **kw: Any) -> dict[str, Any]:  # type: ignore[override]
                return dict(schema)

        plugin_id, name = manifest.id, spec["name"]
        timeout = float(spec.get("timeout_s", 15))

        async def handler(args: _AnyArgs, ctx: ToolContext) -> ToolResult:
            payload = args.model_dump()
            try:
                jsonschema.validate(payload, schema)
            except jsonschema.ValidationError as exc:
                return ToolResult.failure("invalid_arguments", f"Invalid parameters: {exc.message}")
            r = await self._http.post(f"/plugins/{plugin_id}/tools/{name}", json={
                "args": payload, "context": ctx.model_dump(mode="json"), "timeout_s": timeout})
            data = r.json()
            if r.status_code >= 400:
                return ToolResult.failure("plugin_error", str(data.get("error", "sandbox error"))[:500])
            return ToolResult.model_validate(data)

        self.c.tools.register(ToolDefinition(
            name=name, description=spec.get("description", ""), parameters=Params,
            category=spec.get("category", "plugin"), permissions=list(spec.get("permissions") or []),
            side_effect=SideEffect(spec.get("side_effect", "read")),
            requires_confirmation=bool(spec.get("requires_confirmation")), timeout_s=timeout + 5,
        ), handler, owner=plugin_id)

    async def stop_plugin(self, plugin_id: str) -> None:
        self.granted.pop(plugin_id, None)
        self.manifests.pop(plugin_id, None)
        self.c.components.unregister_owner(plugin_id)
        self.c.bus.catalog.unregister_owner(f"plugin:{plugin_id}")
        try:
            await self._http.post(f"/plugins/{plugin_id}/stop")
        except httpx.HTTPError as exc:
            log.warning("sandbox stop failed", plugin=plugin_id, error=str(exc))

    async def health(self, plugin_id: str) -> PluginHealth:
        try:
            r = await self._http.get(f"/plugins/{plugin_id}/health", timeout=10)
            return PluginHealth.model_validate(r.json())
        except Exception as exc:
            return PluginHealth(state=HealthState.FAILED, detail=str(exc))

    async def run_tests(self, files: dict[str, str], timeout_s: float = 90) -> dict[str, Any]:
        if not await self.available():
            raise Unavailable("sandbox service not reachable")
        r = await self._http.post("/tests/run", json={"files": files, "timeout_s": timeout_s},
                                  timeout=timeout_s + 30)
        data: dict[str, Any] = r.json()
        return data
