"""Composition root: builds and wires all components (explicit dependency injection).

This is the only module that knows every component. Components receive their
dependencies through their constructors and never look them up globally.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from typing import Any

from justai_sdk.events import Event

from justai.ai.config import AISettings, default_ai_settings
from justai.ai.router import AIRouter
from justai.ai.usage import UsageTracker
from justai.audio.engine import AudioEngine
from justai.audio.io import TalkbackRoutes
from justai.auth.service import AuthService
from justai.common.crypto import SecretBox, load_or_create_master_key
from justai.common.supervisor import Supervisor
from justai.config import Settings
from justai.conversation.manager import ConversationManager
from justai.db.engine import Database
from justai.db.migrate import upgrade_to_head
from justai.devices.manager import DeviceManager
from justai.devices.service import DeviceService
from justai.display.components import ComponentRegistry
from justai.endpoints.service import EndpointService
from justai.events.bus import EventBus
from justai.events.catalog import build_core_catalog
from justai.events.store import EventStore
from justai.logging import get_logger
from justai.media.go2rtc import Go2rtcClient
from justai.output.router import OutputRouter
from justai.output.topology import LiveTopology
from justai.plugins.manager import PluginManager
from justai.plugins.providers import ProviderRegistry
from justai.rooms.service import RoomService
from justai.system.jobs import JobQueue
from justai.system.store import AuditLog, SecretStore, SettingsStore
from justai.system.telemetry import TelemetryHub
from justai.tools.registry import ConfirmationManager, ToolExecutor, ToolRegistry

log = get_logger(__name__)


class Container:
    """Holds all long-lived services of the core process."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db = Database(settings.resolved_database_url())
        # The shared secrets volume (created by the secrets-init container) is preferred;
        # outside Docker the key lives in the data directory.
        key_file = (settings.secret_key_file if settings.secret_key_file.parent.exists()
                    else settings.data_dir / "secrets" / "master_key")
        master_key = load_or_create_master_key(
            key_file, settings.secret_key.get_secret_value() if settings.secret_key else None)
        self.master_key = master_key
        self.secret_box = SecretBox(master_key)
        self.settings_store = SettingsStore(self.db)
        self.secrets = SecretStore(self.db, self.secret_box)
        self.audit = AuditLog(self.db)
        self.supervisor = Supervisor()
        self.telemetry = TelemetryHub()

        # events / jobs
        self.event_store = EventStore(self.db)
        self.bus = EventBus(build_core_catalog(), self.event_store)
        self.jobs = JobQueue(self.db)

        # registries
        self.providers = ProviderRegistry()
        self.tools = ToolRegistry()
        self.components = ComponentRegistry()

        # domain services
        self.auth = AuthService(self.db, master_key, token_ttl_hours=settings.jwt_ttl_hours)
        self.rooms = RoomService(self.db)
        self.device_records = DeviceService(self.db, self.secrets)
        self.endpoints = EndpointService(self.db)
        self.go2rtc = Go2rtcClient(settings.go2rtc_url, settings.go2rtc_rtsp_url)
        self.devices = DeviceManager(self.device_records, self.providers, self.go2rtc, self.bus,
                                     self.supervisor)
        self.topology = LiveTopology(self.rooms, self.endpoints, self.device_records, self.devices)
        self.output = OutputRouter(self.topology)

        # AI
        self.usage = UsageTracker(self.db)
        self.ai = AIRouter(self.providers, self._load_ai_settings, self.bus, self.usage,
                           audit=self._audit_system)

        # audio / conversation
        self.talkback = TalkbackRoutes()
        self.audio = AudioEngine(self.devices, self.endpoints, self.output, self.providers,
                                 self.go2rtc, self.talkback, self.bus, self.telemetry,
                                 self.supervisor, core_url=settings.core_internal_url)
        self.confirmations = ConfirmationManager(lambda sid: self.conversations.user_turns(sid))
        self.executor = ToolExecutor(self.tools, self.bus, self.db, self.confirmations)
        self.memory: Any = None  # set by _build_extensions
        self.conversations = ConversationManager(
            db=self.db, bus=self.bus, audio=self.audio, endpoints=self.endpoints, rooms=self.rooms,
            router=self.ai, registry=self.tools, executor=self.executor, jobs=self.jobs,
            recall=_LazyRecall(self))
        speaker_model = settings.models_dir / "speaker" / "wespeaker_en_voxceleb_resnet34.onnx"
        if speaker_model.exists():
            from justai.audio.speaker import SpeakerEmbedder

            try:
                self.conversations.voice = SpeakerEmbedder(speaker_model)
                from justai.identity.voice import VoiceProfiles

                self.conversations.voices = VoiceProfiles(self.db, self.conversations.voice)
            except Exception as exc:
                log.warning("speaker model not usable, no voice comparison", error=str(exc))

        # plugins
        from justai.plugins.backend import CoreServicesBackend
        from justai.plugins.sandbox_host import SandboxClient

        sandbox_token = os.environ.get("JUSTAI_SANDBOX_TOKEN") or (
            settings.sandbox_token_file.read_text().strip()
            if settings.sandbox_token_file.exists() else None)
        self.sandbox = SandboxClient(self, settings.sandbox_url, sandbox_token) if sandbox_token else None
        self.plugins = PluginManager(
            self.db, self.bus, self.secrets, self.providers, self.tools, self.components,
            CoreServicesBackend(self), builtin_dir=settings.builtin_plugins_dir,
            install_dir=settings.data_dir / "plugins", sandbox=self.sandbox)
        self.extensions: dict[str, Any] = {}
        self._tasks: list[asyncio.Task[None]] = []

    # ------------------------------------------------------------------ helpers
    async def _load_ai_settings(self) -> AISettings:
        raw = await self.settings_store.get("ai")
        if raw is None:
            has_key = bool(os.environ.get("GOOGLE_API_KEY")) or await self.secrets.has("plugin:gemini:api_key")
            settings = default_ai_settings(has_google_key=has_key)
            await self.settings_store.set("ai", settings)
            return settings
        return AISettings.model_validate(raw)

    async def _autoconfigure_ai(self) -> None:
        from justai.ai.config import fill_empty_roles

        settings = await self._load_ai_settings()
        available: dict[str, set[str]] = {}
        for entry in self.providers.entries():
            available.setdefault(entry.kind, set()).add(entry.id)
        if fill_empty_roles(settings, available):
            await self.settings_store.set("ai", settings)
            self.ai.invalidate()
            log.info("AI roles auto-configured for newly available providers")

    async def _audit_system(self, action: str, detail: dict[str, Any]) -> None:
        await self.audit.record("system", action, None, **detail)

    def _on_provider_change(self, kind: str, provider_id: str, available: bool) -> None:
        self.ai.invalidate()
        if available and kind in ("llm", "realtime", "stt", "tts", "embedding"):
            asyncio.get_running_loop().create_task(self._autoconfigure_ai())
        if kind == "device_driver":
            asyncio.get_running_loop().create_task(
                self.devices.on_driver_change(provider_id, available))
        if kind == "wakeword":
            asyncio.get_running_loop().create_task(self.audio.reload_endpoints())

    async def refresh_topology(self) -> None:
        await self.topology.refresh()
        await self.audio.reload_endpoints()

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        s = self.settings
        s.data_dir.mkdir(parents=True, exist_ok=True)
        await upgrade_to_head(self.db)
        await self.auth.ensure_admin(
            s.admin_username, s.admin_password.get_secret_value() if s.admin_password else None,
            s.data_dir)
        await self.event_store.start()
        await self.usage.start()
        self.providers.on_change(self._on_provider_change)
        await self._build_extensions()
        from justai.tools.builtin import register_builtin_tools

        register_builtin_tools(self)
        await self.plugins.start()
        await self.topology.refresh()
        await self.devices.start()
        if self.conversations.voices is not None:
            await self.conversations.voices.reload()
        self.supervisor.start("go2rtc-streams", self.go2rtc.keep_streams)
        await self.audio.start()
        for ext in self.extensions.values():
            start = getattr(ext, "start", None)
            if start:
                await start()
        await self.jobs.start()

        async def on_device_event(event: Event) -> None:
            await self.topology.refresh()

        self.bus.subscribe("device.status.changed", on_device_event, name="topology-refresh")
        log.info("JuStAI5 core started")

    async def _build_extensions(self) -> None:
        """Optional feature modules (memory, vision, automation, display, ...)."""
        from justai.extensions import build_extensions

        self.extensions = await build_extensions(self)
        self.memory = self.extensions.get("memory")

    async def stop(self) -> None:
        log.info("JuStAI5 core stopping")
        with contextlib.suppress(Exception):
            await self.conversations.end_all()
        for ext in reversed(list(self.extensions.values())):
            stop = getattr(ext, "stop", None)
            if stop:
                with contextlib.suppress(Exception):
                    await stop()
        await self.jobs.stop()
        await self.audio.stop()
        await self.devices.stop()
        await self.plugins.stop()
        await self.supervisor.stop_all()
        await self.usage.stop()
        await self.bus.close()
        await self.event_store.stop()
        await self.go2rtc.close()
        await self.db.dispose()


class _LazyRecall:
    """Memory recall bound late (the memory extension is built after the manager)."""

    def __init__(self, container: Container) -> None:
        self._c = container

    async def recall(self, query: str, *, person_id: str | None, room_id: str | None,
                     limit: int = 6) -> list[str]:
        if self._c.memory is None:
            return []
        result: list[str] = await self._c.memory.recall(query, person_id=person_id,
                                                         room_id=room_id, limit=limit)
        return result
