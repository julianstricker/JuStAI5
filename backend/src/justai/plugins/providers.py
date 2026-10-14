"""Registry of provider implementations contributed by plugins.

One generic registry is used for all port kinds (device drivers, LLMs, STT, ...).
Entries are owned by a plugin and removed when the plugin is disabled, which is
how plugin capabilities "disappear again" (acceptance criterion 17).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from justai_sdk.ports import PROVIDER_KINDS


@dataclass(frozen=True)
class ProviderEntry:
    kind: str
    id: str
    plugin_id: str
    provider: Any


def provider_id_of(provider: Any) -> str:
    for attr in ("provider_id", "driver_id", "discovery_id", "detector_id", "analyzer_id"):
        value = getattr(provider, attr, None)
        if isinstance(value, str):
            return value
    raise ValueError(f"provider {provider!r} has no id attribute")


class ProviderRegistry:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, str], ProviderEntry] = {}
        self._listeners: list[Callable[[str, str, bool], None]] = []

    def register(self, kind: str, provider: Any, plugin_id: str) -> ProviderEntry:
        if kind not in PROVIDER_KINDS:
            raise ValueError(f"unknown provider kind {kind}")
        pid = provider_id_of(provider)
        key = (kind, pid)
        existing = self._entries.get(key)
        if existing and existing.plugin_id != plugin_id:
            raise ValueError(f"{kind} provider '{pid}' already registered by {existing.plugin_id}")
        entry = ProviderEntry(kind, pid, plugin_id, provider)
        self._entries[key] = entry
        for listener in self._listeners:
            listener(kind, pid, True)
        return entry

    def unregister_plugin(self, plugin_id: str) -> list[ProviderEntry]:
        removed = [e for e in self._entries.values() if e.plugin_id == plugin_id]
        for e in removed:
            del self._entries[(e.kind, e.id)]
            for listener in self._listeners:
                listener(e.kind, e.id, False)
        return removed

    def get(self, kind: str, provider_id: str) -> Any | None:
        entry = self._entries.get((kind, provider_id))
        return entry.provider if entry else None

    def entries(self, kind: str | None = None) -> list[ProviderEntry]:
        return sorted(
            (e for e in self._entries.values() if kind is None or e.kind == kind),
            key=lambda e: (e.kind, e.id),
        )

    def all(self, kind: str) -> list[Any]:
        return [e.provider for e in self.entries(kind)]

    def on_change(self, listener: Callable[[str, str, bool], None]) -> None:
        self._listeners.append(listener)
