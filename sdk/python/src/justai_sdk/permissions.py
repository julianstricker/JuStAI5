"""Permission vocabulary shared by plugins, tools and the core.

Permissions are plain dotted strings so that plugins can declare them in their
manifest. The core only grants permissions that appear in :data:`KNOWN_PERMISSIONS`
or that a plugin defines in its own namespace (``plugin.<plugin_id>.*``).
"""

from __future__ import annotations

from enum import StrEnum


class Permission(StrEnum):
    # Perception
    CAMERA_READ = "camera.read"
    CAMERA_PTZ = "camera.ptz"
    MICROPHONE_READ = "microphone.read"
    # Output
    SPEAKER_WRITE = "speaker.write"
    DISPLAY_WRITE = "display.write"
    OUTPUT_CROSS_ROOM = "output.cross_room"
    # Knowledge
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    IDENTITY_READ = "identity.read"
    IDENTITY_MANAGE = "identity.manage"
    BIOMETRIC_ENROLL = "biometric.enroll"
    # Behaviour
    AUTOMATION_MANAGE = "automation.manage"
    EVENTS_PUBLISH = "events.publish"
    EVENTS_SUBSCRIBE = "events.subscribe"
    ASSISTANT_INVOKE = "assistant.invoke"
    # Infrastructure
    DEVICES_READ = "devices.read"
    DEVICES_MANAGE = "devices.manage"
    DEVICES_CONTROL = "devices.control"
    DEVICES_PROVIDE = "devices.provide"
    NETWORK_HTTP = "network.http"
    NETWORK_LAN = "network.lan"
    NETWORK_DISCOVERY = "network.discovery"
    STORAGE_PLUGIN = "storage.plugin"
    AI_INVOKE = "ai.invoke"
    AI_PROVIDE = "ai.provide"
    VISION_ANALYZE = "vision.analyze"
    VISION_MANAGE = "vision.manage"
    TOOLS_PROVIDE = "tools.provide"
    TOOLS_DEVELOP = "tools.develop"
    SYSTEM_READ = "system.read"
    SYSTEM_MANAGE = "system.manage"


PERMISSION_DESCRIPTIONS: dict[str, str] = {
    Permission.CAMERA_READ: "Read camera images and snapshots",
    Permission.CAMERA_PTZ: "Control movable cameras",
    Permission.MICROPHONE_READ: "Read microphone audio",
    Permission.SPEAKER_WRITE: "Play audio through speakers (via the output router)",
    Permission.DISPLAY_WRITE: "Show content on screens (via the output router)",
    Permission.OUTPUT_CROSS_ROOM: "Output in a room other than the one of the request",
    Permission.MEMORY_READ: "Read memories",
    Permission.MEMORY_WRITE: "Store, change and delete memories",
    Permission.IDENTITY_READ: "Look up known people",
    Permission.IDENTITY_MANAGE: "Manage person profiles",
    Permission.BIOMETRIC_ENROLL: "Create biometric profiles (face/voice)",
    Permission.AUTOMATION_MANAGE: "Create, change and delete automations",
    Permission.EVENTS_PUBLISH: "Publish events",
    Permission.EVENTS_SUBSCRIBE: "Subscribe to events",
    Permission.ASSISTANT_INVOKE: "Actively trigger the assistant (proactive conversations)",
    Permission.DEVICES_READ: "Look up devices and capabilities",
    Permission.DEVICES_MANAGE: "Add and configure devices",
    Permission.DEVICES_CONTROL: "Operate devices (privacy mode, reconnect, test tone, listening pause)",
    Permission.DEVICES_PROVIDE: "Provide device drivers",
    Permission.NETWORK_HTTP: "HTTP requests to allowed hosts",
    Permission.NETWORK_LAN: "Connections to devices on the local network",
    Permission.NETWORK_DISCOVERY: "Network search in authorised ranges",
    Permission.STORAGE_PLUGIN: "Own, isolated data storage",
    Permission.AI_INVOKE: "Call AI models",
    Permission.AI_PROVIDE: "Provide AI providers",
    Permission.VISION_ANALYZE: "Run image analysis",
    Permission.VISION_MANAGE: "Configure analysis tasks",
    Permission.TOOLS_PROVIDE: "Provide tools for the assistant",
    Permission.TOOLS_DEVELOP: "Generate and test new tools",
    Permission.SYSTEM_READ: "Read the system status",
    Permission.SYSTEM_MANAGE: "Change the system configuration",
}

KNOWN_PERMISSIONS: frozenset[str] = frozenset(p.value for p in Permission)

# Permissions that untrusted (sandboxed) plugins may never be granted.
TRUSTED_ONLY_PERMISSIONS: frozenset[str] = frozenset(
    {
        Permission.DEVICES_PROVIDE,
        Permission.DEVICES_CONTROL,
        Permission.AI_PROVIDE,
        Permission.NETWORK_LAN,
        Permission.NETWORK_DISCOVERY,
        Permission.SYSTEM_MANAGE,
        Permission.BIOMETRIC_ENROLL,
        Permission.TOOLS_DEVELOP,
    }
)


def is_valid_permission(value: str, plugin_id: str | None = None) -> bool:
    if value in KNOWN_PERMISSIONS:
        return True
    return plugin_id is not None and value.startswith(f"plugin.{plugin_id}.")
