"""Plugin manifest model (``plugin.yaml``)."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from justai_sdk.permissions import TRUSTED_ONLY_PERMISSIONS, is_valid_permission

SDK_API_VERSION = "1.0"
MANIFEST_FILENAME = "plugin.yaml"

_PLUGIN_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")


class PluginType(StrEnum):
    DEVICE = "device"
    DISCOVERY = "discovery"
    MEDIA = "media"
    AI_PROVIDER = "ai_provider"
    REALTIME_AI = "realtime_ai"
    STT = "stt"
    TTS = "tts"
    WAKEWORD = "wakeword"
    EMBEDDING = "embedding"
    VISION = "vision"
    RECOGNITION = "recognition"
    PTZ = "ptz"
    DISPLAY = "display"
    TOOL = "tool"
    EVENT_SOURCE = "event_source"
    INTEGRATION = "integration"


class TrustLevel(StrEnum):
    BUILTIN = "builtin"  # shipped with JuStAI5, runs in-process
    TRUSTED = "trusted"  # explicitly trusted by an admin, runs in-process
    UNTRUSTED = "untrusted"  # third-party / generated code, runs in the sandbox


class RuntimeMode(StrEnum):
    IN_PROCESS = "in_process"
    SANDBOX = "sandbox"


class PluginDependency(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    version: str = ""  # PEP 440 specifier, e.g. ">=1.0,<2"
    optional: bool = False

    @field_validator("version")
    @classmethod
    def _valid_spec(cls, v: str) -> str:
        if v:
            try:
                SpecifierSet(v)
            except InvalidSpecifier as exc:
                raise ValueError(f"invalid version specifier: {v}") from exc
        return v


class RuntimeRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid")

    python: str = ">=3.12"
    memory_mb: int = 256
    gpu: str = "none"  # none | optional | required
    binaries: list[str] = Field(default_factory=list)  # e.g. ffmpeg


class PluginManifest(BaseModel):
    """Machine-readable description of a plugin.

    The manifest is validated before any plugin code is imported, so the core can
    check compatibility, dependencies and permissions without executing it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = ""
    homepage: str = ""
    types: list[PluginType]
    api: str = Field(default=">=1.0,<2.0", description="Compatible SDK API versions")
    entrypoint: str = Field(description="'module.path:ClassName' relative to the plugin dir")
    trust: TrustLevel = TrustLevel.UNTRUSTED
    runtime: RuntimeMode | None = None
    provides: list[str] = Field(
        default_factory=list,
        description="Capabilities offered, e.g. 'tool:weather.current', 'llm:gemini'",
    )
    permissions: list[str] = Field(default_factory=list)
    network_allowlist: list[str] = Field(
        default_factory=list, description="Hostnames reachable with network.http"
    )
    dependencies: list[PluginDependency] = Field(default_factory=list)
    config_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    secret_fields: list[str] = Field(
        default_factory=list, description="Config keys stored encrypted and never logged"
    )
    requirements: RuntimeRequirements = Field(default_factory=RuntimeRequirements)
    display_components: list[str] = Field(default_factory=list)
    default_enabled: bool = Field(
        default=False, description="Builtin plugins: enable automatically on first start"
    )

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        if not _PLUGIN_ID_RE.match(v):
            raise ValueError("plugin id must match ^[a-z][a-z0-9_-]{1,62}$")
        return v

    @field_validator("version")
    @classmethod
    def _valid_version(cls, v: str) -> str:
        try:
            Version(v)
        except InvalidVersion as exc:
            raise ValueError(f"invalid version: {v}") from exc
        return v

    @field_validator("api")
    @classmethod
    def _valid_api(cls, v: str) -> str:
        try:
            SpecifierSet(v)
        except InvalidSpecifier as exc:
            raise ValueError(f"invalid api specifier: {v}") from exc
        return v

    @field_validator("entrypoint")
    @classmethod
    def _valid_entrypoint(cls, v: str) -> str:
        if ":" not in v or v.startswith(":") or v.endswith(":"):
            raise ValueError("entrypoint must look like 'module.path:ClassName'")
        return v

    @model_validator(mode="after")
    def _check_consistency(self) -> PluginManifest:
        for perm in self.permissions:
            if not is_valid_permission(perm, self.id):
                raise ValueError(f"unknown permission: {perm}")
        if self.effective_runtime is RuntimeMode.SANDBOX:
            forbidden = sorted(set(self.permissions) & TRUSTED_ONLY_PERMISSIONS)
            if forbidden:
                raise ValueError(
                    f"sandboxed plugins cannot request trusted-only permissions: {forbidden}"
                )
        if self.trust is TrustLevel.UNTRUSTED and self.runtime is RuntimeMode.IN_PROCESS:
            raise ValueError("untrusted plugins cannot run in-process")
        return self

    @property
    def effective_runtime(self) -> RuntimeMode:
        if self.runtime is not None:
            return self.runtime
        return RuntimeMode.SANDBOX if self.trust is TrustLevel.UNTRUSTED else RuntimeMode.IN_PROCESS

    def is_api_compatible(self, api_version: str = SDK_API_VERSION) -> bool:
        return Version(api_version) in SpecifierSet(self.api)


def load_manifest(plugin_dir: Path) -> PluginManifest:
    path = plugin_dir / MANIFEST_FILENAME
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a mapping")
    return PluginManifest.model_validate(data)
