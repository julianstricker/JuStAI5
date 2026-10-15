"""Plugin lifecycle: install, enable, configure, update, disable, remove.

* Manifests are validated before code is imported.
* API compatibility and dependencies are checked on enable.
* Plugins only receive permissions that an admin granted (subset of the manifest).
* Failures in setup/start/health mark the plugin as failed and release everything
  it registered; the rest of the assistant keeps running.
* Untrusted plugins never run in-process; they are delegated to the sandbox host.
"""

from __future__ import annotations

import asyncio
import builtins
import contextlib
import io
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import jsonschema
from justai_sdk.events import Event, EventSource
from justai_sdk.manifest import (
    MANIFEST_FILENAME,
    SDK_API_VERSION,
    PluginManifest,
    RuntimeMode,
    TrustLevel,
)
from justai_sdk.permissions import TRUSTED_ONLY_PERMISSIONS
from justai_sdk.plugin import HealthState, Plugin, PluginHealth
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from sqlalchemy import delete, select

from justai.common.errors import Conflict, NotFound, ValidationFailed
from justai.db.engine import Database
from justai.db.models import InstalledPlugin, PluginDocument
from justai.events.bus import EventBus
from justai.logging import get_logger
from justai.plugins.context import (
    DisplayComponentRegistry,
    InProcessPluginContext,
    ServicesBackend,
)
from justai.plugins.loader import PluginSource, discover, load_plugin_class, unload_plugin_modules
from justai.plugins.providers import ProviderRegistry
from justai.system.store import SecretStore
from justai.tools.registry import ToolRegistry

log = get_logger(__name__)


class SandboxHost(Protocol):
    async def start_plugin(self, manifest: PluginManifest, path: Path, config: dict[str, Any],
                           granted: frozenset[str]) -> None: ...

    async def stop_plugin(self, plugin_id: str) -> None: ...

    async def health(self, plugin_id: str) -> PluginHealth: ...


@dataclass
class PluginRuntime:
    manifest: PluginManifest
    path: Path
    instance: Plugin | None = None
    context: InProcessPluginContext | None = None
    sandboxed: bool = False
    health: PluginHealth = field(default_factory=PluginHealth)


class PluginManager:
    HEALTH_INTERVAL_S = 60.0

    def __init__(
        self,
        db: Database,
        bus: EventBus,
        secrets: SecretStore,
        providers: ProviderRegistry,
        tools: ToolRegistry,
        components: DisplayComponentRegistry,
        backend: ServicesBackend,
        *,
        builtin_dir: Path,
        install_dir: Path,
        sandbox: SandboxHost | None = None,
    ) -> None:
        self.db = db
        self.bus = bus
        self.secrets = secrets
        self.providers = providers
        self.tools = tools
        self.components = components
        self.backend = backend
        self.builtin_dir = builtin_dir
        self.install_dir = install_dir
        self.sandbox = sandbox
        self._runtimes: dict[str, PluginRuntime] = {}
        self._lock = asyncio.Lock()
        self._health_task: asyncio.Task[None] | None = None

    # ---------------------------------------------------------------- startup
    async def start(self) -> None:
        await self.sync_builtin()
        async with self.db.session() as s:
            rows = (await s.scalars(select(InstalledPlugin).where(InstalledPlugin.enabled))).all()
        for row in self._dependency_order(rows):
            try:
                await self._start_plugin(row.id)
            except Exception as exc:
                log.error("plugin failed to start", plugin=row.id, error=str(exc))
        self._health_task = asyncio.create_task(self._health_loop(), name="plugin-health")

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        for plugin_id in reversed(list(self._runtimes)):
            await self._stop_plugin(plugin_id)

    async def sync_builtin(self) -> None:
        """Register builtin plugins; update their manifest when the image changed."""
        for source in discover(self.builtin_dir, "builtin"):
            m = source.manifest
            async with self.db.session() as s:
                row = await s.get(InstalledPlugin, m.id)
                if row is None:
                    s.add(InstalledPlugin(
                        id=m.id, version=m.version, source="builtin", path=str(source.path),
                        enabled=m.default_enabled, config=_defaults(m.config_schema),
                        granted_permissions=list(m.permissions),
                        manifest=m.model_dump(mode="json"), status="installed",
                    ))
                elif row.source == "builtin":
                    if row.version != m.version:
                        # New builtin version keeps its config. If the admin never revoked a
                        # permission, newly requested ones are granted too; otherwise only the
                        # still-requested subset of the previous grant is kept.
                        previous = set(row.granted_permissions)
                        never_revoked = previous >= set(row.manifest.get("permissions", []))
                        granted = set(m.permissions) if never_revoked else previous & set(m.permissions)
                        row.granted_permissions = sorted(granted)
                    row.version, row.path = m.version, str(source.path)
                    row.manifest = m.model_dump(mode="json")

    # ------------------------------------------------------------------ queries
    async def list(self) -> builtins.list[dict[str, Any]]:
        async with self.db.session() as s:
            rows = (await s.scalars(select(InstalledPlugin).order_by(InstalledPlugin.id))).all()
        out = []
        for row in rows:
            rt = self._runtimes.get(row.id)
            out.append({
                "id": row.id, "version": row.version, "source": row.source,
                "enabled": row.enabled, "status": row.status, "error": row.error,
                "manifest": row.manifest, "config": row.config,
                "granted_permissions": row.granted_permissions,
                "running": rt is not None,
                "health": rt.health.model_dump() if rt else None,
                "provides": {
                    "tools": [t.definition.name for t in self.tools.list() if t.owner == row.id],
                    "providers": [f"{e.kind}:{e.id}" for e in self.providers.entries()
                                  if e.plugin_id == row.id],
                },
            })
        return out

    async def get_row(self, plugin_id: str) -> InstalledPlugin:
        async with self.db.session() as s:
            row = await s.get(InstalledPlugin, plugin_id)
        if row is None:
            raise NotFound(f"plugin {plugin_id} not installed")
        return row

    def runtime(self, plugin_id: str) -> PluginRuntime | None:
        return self._runtimes.get(plugin_id)

    # -------------------------------------------------------------- lifecycle API
    async def enable(self, plugin_id: str) -> None:
        async with self._lock:
            row = await self.get_row(plugin_id)
            manifest = PluginManifest.model_validate(row.manifest)
            await self._check_dependencies(manifest)
            await self._set(plugin_id, enabled=True)
            await self._start_plugin(plugin_id)

    async def disable(self, plugin_id: str) -> None:
        async with self._lock:
            dependants = await self._enabled_dependants(plugin_id)
            if dependants:
                raise Conflict(f"plugins depend on {plugin_id}: {', '.join(dependants)}")
            await self._stop_plugin(plugin_id)
            await self._set(plugin_id, enabled=False, status="disabled", error=None)

    async def configure(self, plugin_id: str, config: dict[str, Any],
                        granted_permissions: builtins.list[str] | None = None) -> None:
        row = await self.get_row(plugin_id)
        manifest = PluginManifest.model_validate(row.manifest)
        public = {k: v for k, v in config.items() if k not in manifest.secret_fields}
        secret = {k: v for k, v in config.items() if k in manifest.secret_fields}
        merged = {**row.config, **public}
        stored_secrets = await self.secrets.get_many(f"plugin:{plugin_id}:")
        effective_secrets = {**stored_secrets, **{k: v for k, v in secret.items() if v not in (None, "")}}
        try:
            jsonschema.validate({**merged, **effective_secrets}, manifest.config_schema)
        except jsonschema.ValidationError as exc:
            raise ValidationFailed(f"invalid configuration: {exc.message}") from exc
        update: dict[str, Any] = {"config": merged}
        if granted_permissions is not None:
            unknown = set(granted_permissions) - set(manifest.permissions)
            if unknown:
                raise ValidationFailed(f"permissions not requested by the plugin: {sorted(unknown)}")
            update["granted_permissions"] = sorted(granted_permissions)
        await self._set(plugin_id, **update)
        for k, v in secret.items():
            if v not in (None, ""):
                await self.secrets.set(f"plugin:{plugin_id}:{k}", str(v))
        rt = self._runtimes.get(plugin_id)
        if rt is not None:
            applied = False
            if rt.instance is not None and granted_permissions is None:
                with contextlib.suppress(Exception):
                    full = await self._full_config(plugin_id, merged)
                    if rt.context:
                        rt.context.config = full
                    applied = await rt.instance.on_config_changed(full)
            if not applied:
                async with self._lock:
                    await self._stop_plugin(plugin_id)
                    await self._start_plugin(plugin_id)

    async def install_archive(self, data: bytes, *, origin: str = "uploaded") -> PluginManifest:
        """Install (or update) a plugin from a zip archive. Uploaded plugins are untrusted."""
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            for name in names:
                if name.startswith("/") or ".." in Path(name).parts:
                    raise ValidationFailed("archive contains unsafe paths")
            prefix = ""
            if MANIFEST_FILENAME not in names:
                roots = {n.split("/", 1)[0] for n in names}
                if len(roots) == 1 and f"{next(iter(roots))}/{MANIFEST_FILENAME}" in names:
                    prefix = next(iter(roots)) + "/"
                else:
                    raise ValidationFailed("archive has no plugin.yaml")
            import yaml

            raw = yaml.safe_load(zf.read(prefix + MANIFEST_FILENAME))
            manifest = PluginManifest.model_validate(raw)
            if manifest.trust is not TrustLevel.UNTRUSTED:
                manifest = manifest.model_copy(update={"trust": TrustLevel.UNTRUSTED, "runtime": None})
                PluginManifest.model_validate(manifest.model_dump())  # re-check permission limits
            target = self.install_dir / manifest.id / manifest.version
            if target.exists():
                shutil.rmtree(target)
            target.mkdir(parents=True)
            for name in names:
                if not name.startswith(prefix) or name.endswith("/"):
                    continue
                dest = target / name[len(prefix):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
        return await self.register_installed(manifest, target, origin)

    async def register_installed(self, manifest: PluginManifest, path: Path,
                                 origin: str) -> PluginManifest:
        async with self.db.session() as s:
            row = await s.get(InstalledPlugin, manifest.id)
            if row is not None and row.source == "builtin":
                raise Conflict("builtin plugins cannot be replaced by uploads")
        was_enabled = row.enabled if row else False
        if row is not None:
            await self._stop_plugin(manifest.id)
        async with self.db.session() as s:
            row = await s.get(InstalledPlugin, manifest.id)
            if row is None:
                s.add(InstalledPlugin(
                    id=manifest.id, version=manifest.version, source=origin, path=str(path),
                    enabled=False, config=_defaults(manifest.config_schema),
                    granted_permissions=[], manifest=manifest.model_dump(mode="json"),
                    status="installed",
                ))
            else:  # update: keep config and only previously granted permissions
                row.version, row.path, row.source = manifest.version, str(path), origin
                row.manifest = manifest.model_dump(mode="json")
                row.granted_permissions = sorted(set(row.granted_permissions) & set(manifest.permissions))
                row.status = "installed"
        if was_enabled:
            await self.enable(manifest.id)
        return manifest

    async def remove(self, plugin_id: str) -> None:
        row = await self.get_row(plugin_id)
        if row.source == "builtin":
            raise Conflict("builtin plugins can be disabled but not removed")
        await self.disable(plugin_id)
        async with self.db.session() as s:
            await s.execute(delete(PluginDocument).where(PluginDocument.plugin_id == plugin_id))
            await s.execute(delete(InstalledPlugin).where(InstalledPlugin.id == plugin_id))
        await self.secrets.delete_prefix(f"plugin:{plugin_id}:")
        shutil.rmtree(self.install_dir / plugin_id, ignore_errors=True)

    # ---------------------------------------------------------------- internals
    async def _start_plugin(self, plugin_id: str) -> None:
        if plugin_id in self._runtimes:
            return
        row = await self.get_row(plugin_id)
        manifest = PluginManifest.model_validate(row.manifest)
        if not manifest.is_api_compatible(SDK_API_VERSION):
            await self._fail(plugin_id, f"incompatible SDK API (needs {manifest.api})")
            return
        granted = frozenset(row.granted_permissions) & frozenset(manifest.permissions)
        config = await self._full_config(plugin_id, row.config)
        path = Path(row.path)
        sandboxed = manifest.effective_runtime is RuntimeMode.SANDBOX
        if sandboxed:
            granted = granted - TRUSTED_ONLY_PERMISSIONS
            if self.sandbox is None:
                await self._fail(plugin_id, "sandbox runtime not available")
                return
            try:
                await self.sandbox.start_plugin(manifest, path, config, granted)
            except Exception as exc:
                await self._fail(plugin_id, f"sandbox start failed: {exc}")
                return
            self._runtimes[plugin_id] = PluginRuntime(manifest, path, sandboxed=True)
            await self._set(plugin_id, status="running", error=None)
            await self._announce(plugin_id, "running")
            return

        ctx = InProcessPluginContext(
            manifest, config, granted, db=self.db, bus=self.bus, providers=self.providers,
            tools=self.tools, components=self.components, backend=self.backend, data_dir=path,
        )
        runtime = PluginRuntime(manifest, path, context=ctx)
        try:
            cls = load_plugin_class(PluginSource(manifest, path, row.source))
            runtime.instance = cls(ctx)
            await asyncio.wait_for(runtime.instance.setup(), timeout=120)
            await asyncio.wait_for(runtime.instance.start(), timeout=120)
        except Exception as exc:
            log.error("plugin start failed", plugin=plugin_id, error=str(exc), exc_info=True)
            with contextlib.suppress(Exception):
                if runtime.instance:
                    await runtime.instance.stop()
            await ctx.release()
            unload_plugin_modules(plugin_id)
            await self._fail(plugin_id, f"{type(exc).__name__}: {exc}")
            return
        self._runtimes[plugin_id] = runtime
        await self._set(plugin_id, status="running", error=None)
        await self._announce(plugin_id, "running")

    async def _stop_plugin(self, plugin_id: str) -> None:
        runtime = self._runtimes.pop(plugin_id, None)
        if runtime is None:
            return
        if runtime.sandboxed and self.sandbox is not None:
            with contextlib.suppress(Exception):
                await self.sandbox.stop_plugin(plugin_id)
            self.tools.unregister_owner(plugin_id)
        if runtime.instance is not None:
            try:
                await asyncio.wait_for(runtime.instance.stop(), timeout=30)
            except Exception as exc:
                log.warning("plugin stop failed", plugin=plugin_id, error=str(exc))
        if runtime.context is not None:
            await runtime.context.release()
        unload_plugin_modules(plugin_id)
        await self._announce(plugin_id, "stopped")

    async def _health_loop(self) -> None:
        while True:
            await asyncio.sleep(self.HEALTH_INTERVAL_S)
            for plugin_id, rt in list(self._runtimes.items()):
                try:
                    if rt.sandboxed and self.sandbox:
                        rt.health = await asyncio.wait_for(self.sandbox.health(plugin_id), 10)
                    elif rt.instance:
                        rt.health = await asyncio.wait_for(rt.instance.health(), 10)
                except Exception as exc:
                    rt.health = PluginHealth(state=HealthState.FAILED, detail=str(exc))
                if rt.health.state is HealthState.FAILED:
                    log.warning("plugin unhealthy, restarting", plugin=plugin_id,
                                detail=rt.health.detail)
                    async with self._lock:
                        await self._stop_plugin(plugin_id)
                        await self._start_plugin(plugin_id)

    async def _full_config(self, plugin_id: str, config: dict[str, Any]) -> dict[str, Any]:
        return {**config, **await self.secrets.get_many(f"plugin:{plugin_id}:")}

    async def _check_dependencies(self, manifest: PluginManifest) -> None:
        async with self.db.session() as s:
            rows = {r.id: r for r in (await s.scalars(select(InstalledPlugin))).all()}
        for dep in manifest.dependencies:
            row = rows.get(dep.id)
            if row is None or not row.enabled:
                if dep.optional:
                    continue
                raise ValidationFailed(f"dependency {dep.id} is not installed/enabled")
            if dep.version and Version(row.version) not in SpecifierSet(dep.version):
                raise ValidationFailed(f"dependency {dep.id} {row.version} does not satisfy {dep.version}")

    async def _enabled_dependants(self, plugin_id: str) -> builtins.list[str]:
        async with self.db.session() as s:
            rows = (await s.scalars(select(InstalledPlugin).where(InstalledPlugin.enabled))).all()
        return [r.id for r in rows if any(
            d.get("id") == plugin_id and not d.get("optional")
            for d in r.manifest.get("dependencies", []))]

    @staticmethod
    def _dependency_order(rows: Any) -> builtins.list[InstalledPlugin]:
        by_id = {r.id: r for r in rows}
        ordered: builtins.list[InstalledPlugin] = []
        seen: set[str] = set()

        def visit(r: InstalledPlugin, stack: tuple[str, ...]) -> None:
            if r.id in seen or r.id in stack:
                return
            for d in r.manifest.get("dependencies", []):
                if d.get("id") in by_id:
                    visit(by_id[d["id"]], (*stack, r.id))
            seen.add(r.id)
            ordered.append(r)

        for r in rows:
            visit(r, ())
        return ordered

    async def _set(self, plugin_id: str, **values: Any) -> None:
        async with self.db.session() as s:
            row = await s.get(InstalledPlugin, plugin_id)
            if row is None:
                raise NotFound(f"plugin {plugin_id} not installed")
            for k, v in values.items():
                setattr(row, k, v)

    async def _fail(self, plugin_id: str, error: str) -> None:
        await self._set(plugin_id, status="failed", error=error)
        await self._announce(plugin_id, "failed", error)

    async def _announce(self, plugin_id: str, status: str, error: str | None = None) -> None:
        await self.bus.publish(Event(
            type="plugin.status.changed",
            source=EventSource(kind="plugin", plugin_id=plugin_id),
            payload={"plugin_id": plugin_id, "status": status, "error": error},
        ))


def _defaults(schema: dict[str, Any]) -> dict[str, Any]:
    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    return {k: v["default"] for k, v in props.items() if isinstance(v, dict) and "default" in v}
