"""Role based access control.

Two kinds of principals exist:

* **Admin UI users** authenticate with username + password (role admin/resident/guest).
* **Conversation participants** are not authenticated. A conversation gets the
  default role of its interaction endpoint. Recognising a person (face/voice) can
  personalise the conversation (own memories), but biometrics alone never unlock
  permissions listed in :data:`BIOMETRIC_INSUFFICIENT`.
"""

from __future__ import annotations

from enum import StrEnum

from justai_sdk.permissions import KNOWN_PERMISSIONS, Permission


class Role(StrEnum):
    ADMIN = "admin"
    RESIDENT = "resident"
    GUEST = "guest"


_RESIDENT: frozenset[str] = frozenset(
    {
        Permission.CAMERA_READ,
        Permission.CAMERA_PTZ,
        Permission.SPEAKER_WRITE,
        Permission.DISPLAY_WRITE,
        Permission.OUTPUT_CROSS_ROOM,
        Permission.MEMORY_READ,
        Permission.MEMORY_WRITE,
        Permission.IDENTITY_READ,
        Permission.BIOMETRIC_ENROLL,
        Permission.AUTOMATION_MANAGE,
        Permission.ASSISTANT_INVOKE,
        Permission.DEVICES_READ,
        Permission.DEVICES_CONTROL,
        Permission.NETWORK_HTTP,
        Permission.AI_INVOKE,
        Permission.VISION_ANALYZE,
        Permission.VISION_MANAGE,
        Permission.TOOLS_DEVELOP,
        Permission.SYSTEM_READ,
        Permission.EVENTS_SUBSCRIBE,
    }
)

_GUEST: frozenset[str] = frozenset(
    {
        Permission.SPEAKER_WRITE,
        Permission.DISPLAY_WRITE,
        Permission.DEVICES_READ,
        Permission.NETWORK_HTTP,
        Permission.AI_INVOKE,
        Permission.SYSTEM_READ,
    }
)

ROLE_PERMISSIONS: dict[Role, frozenset[str]] = {
    Role.ADMIN: KNOWN_PERMISSIONS,
    Role.RESIDENT: _RESIDENT,
    Role.GUEST: _GUEST,
}

# Never granted on the basis of a recognised face/voice alone (requirement 13.6).
BIOMETRIC_INSUFFICIENT: frozenset[str] = frozenset(
    {
        Permission.SYSTEM_MANAGE,
        Permission.DEVICES_MANAGE,
        Permission.IDENTITY_MANAGE,
        Permission.DEVICES_PROVIDE,
        Permission.AI_PROVIDE,
    }
)


def permissions_for(role: str) -> frozenset[str]:
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def conversation_permissions(endpoint_role: str, person_role: str | None) -> frozenset[str]:
    """Effective permissions of a spoken conversation.

    The endpoint role is the baseline. A recognised person may raise it up to the
    resident level but never to administrative permissions.
    """
    base = permissions_for(endpoint_role)
    if person_role:
        base = base | (permissions_for(person_role) & _RESIDENT)
    return frozenset(base - BIOMETRIC_INSUFFICIENT)
