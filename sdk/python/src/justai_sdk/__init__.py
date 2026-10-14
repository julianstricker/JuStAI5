"""JuStAI5 plugin SDK.

Plugins depend only on this package. It contains the manifest model, the
permission vocabulary, the event model, tool definitions and the capability ports
(device drivers, AI providers, vision, PTZ, displays, wakeword, discovery).
"""

from justai_sdk.audio import AudioChunk
from justai_sdk.events import Event, EventPriority, EventSource, new_id
from justai_sdk.manifest import SDK_API_VERSION, PluginManifest, PluginType, TrustLevel
from justai_sdk.permissions import Permission
from justai_sdk.plugin import (
    DisplayComponentSpec,
    PermissionDenied,
    Plugin,
    PluginContext,
    PluginError,
    PluginHealth,
)
from justai_sdk.tools import SideEffect, ToolContext, ToolDefinition, ToolResult

__all__ = [
    "SDK_API_VERSION",
    "AudioChunk",
    "DisplayComponentSpec",
    "Event",
    "EventPriority",
    "EventSource",
    "PermissionDenied",
    "Permission",
    "Plugin",
    "PluginContext",
    "PluginError",
    "PluginHealth",
    "PluginManifest",
    "PluginType",
    "SideEffect",
    "ToolContext",
    "ToolDefinition",
    "ToolResult",
    "TrustLevel",
    "new_id",
]
