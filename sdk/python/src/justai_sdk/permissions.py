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
    Permission.CAMERA_READ: "Kamerabilder und Snapshots lesen",
    Permission.CAMERA_PTZ: "Bewegliche Kameras steuern",
    Permission.MICROPHONE_READ: "Mikrofon-Audio lesen",
    Permission.SPEAKER_WRITE: "Audio über Lautsprecher ausgeben (über den Output Router)",
    Permission.DISPLAY_WRITE: "Inhalte auf Bildschirmen darstellen (über den Output Router)",
    Permission.OUTPUT_CROSS_ROOM: "Ausgaben in einem anderen Raum als dem der Anfrage",
    Permission.MEMORY_READ: "Erinnerungen lesen",
    Permission.MEMORY_WRITE: "Erinnerungen speichern, ändern und löschen",
    Permission.IDENTITY_READ: "Bekannte Personen abfragen",
    Permission.IDENTITY_MANAGE: "Personenprofile verwalten",
    Permission.BIOMETRIC_ENROLL: "Biometrische Profile (Gesicht/Stimme) anlegen",
    Permission.AUTOMATION_MANAGE: "Automationen anlegen, ändern und löschen",
    Permission.EVENTS_PUBLISH: "Ereignisse veröffentlichen",
    Permission.EVENTS_SUBSCRIBE: "Ereignisse abonnieren",
    Permission.ASSISTANT_INVOKE: "Den Assistenten aktiv auslösen (proaktive Gespräche)",
    Permission.DEVICES_READ: "Geräte und Fähigkeiten abfragen",
    Permission.DEVICES_MANAGE: "Geräte anlegen und konfigurieren",
    Permission.DEVICES_PROVIDE: "Gerätetreiber bereitstellen",
    Permission.NETWORK_HTTP: "HTTP-Anfragen an erlaubte Hosts",
    Permission.NETWORK_LAN: "Verbindungen zu Geräten im lokalen Netz",
    Permission.NETWORK_DISCOVERY: "Netzwerksuche in autorisierten Bereichen",
    Permission.STORAGE_PLUGIN: "Eigener, isolierter Datenspeicher",
    Permission.AI_INVOKE: "KI-Modelle aufrufen",
    Permission.AI_PROVIDE: "KI-Provider bereitstellen",
    Permission.VISION_ANALYZE: "Bildanalyse ausführen",
    Permission.VISION_MANAGE: "Analyseaufgaben konfigurieren",
    Permission.TOOLS_PROVIDE: "Werkzeuge für den Assistenten bereitstellen",
    Permission.TOOLS_DEVELOP: "Neue Werkzeuge generieren und testen",
    Permission.SYSTEM_READ: "Systemstatus lesen",
    Permission.SYSTEM_MANAGE: "Systemkonfiguration ändern",
}

KNOWN_PERMISSIONS: frozenset[str] = frozenset(p.value for p in Permission)

# Permissions that untrusted (sandboxed) plugins may never be granted.
TRUSTED_ONLY_PERMISSIONS: frozenset[str] = frozenset(
    {
        Permission.DEVICES_PROVIDE,
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
