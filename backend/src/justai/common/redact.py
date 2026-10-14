"""Redaction of secrets in logs, events and API responses."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_KEY_RE = re.compile(
    r"(pass(word)?|secret|token|api[_-]?key|authorization|credential|private[_-]?key|cookie)",
    re.IGNORECASE,
)
# user:password@ inside URLs (rtsp://, tapo://, http:// ...)
URL_CREDENTIALS_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<creds>[^/@\s\"']+)@", re.I)
BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+")
GOOGLE_KEY_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]{16,}")

REDACTED = "***"


def redact_text(text: str) -> str:
    text = URL_CREDENTIALS_RE.sub(lambda m: f"{m.group('scheme')}{REDACTED}@", text)
    text = BEARER_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    text = GOOGLE_KEY_RE.sub(REDACTED, text)
    return OPENAI_KEY_RE.sub(REDACTED, text)


def redact(value: Any, *, extra_keys: frozenset[str] = frozenset()) -> Any:
    """Recursively redact secret-looking keys and credentials embedded in strings."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key in extra_keys or (SECRET_KEY_RE.search(key) and not isinstance(v, Mapping)):
                out[key] = REDACTED if v not in (None, "") else v
            else:
                out[key] = redact(v, extra_keys=extra_keys)
        return out
    if isinstance(value, list | tuple):
        return [redact(v, extra_keys=extra_keys) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
