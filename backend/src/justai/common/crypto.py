"""Encryption of secrets at rest (API keys, device passwords)."""

from __future__ import annotations

import base64
import hashlib
import secrets
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, master_key: str) -> None:
        # Derive a Fernet key from an arbitrary-length master secret.
        digest = hashlib.sha256(("justai5-secretbox:" + master_key).encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("secret cannot be decrypted (wrong master key?)") from exc


def load_or_create_master_key(path: Path, explicit: str | None) -> str:
    """Use the explicit key, else the key file; create the file on first start."""
    if explicit:
        return explicit
    if path.exists():
        return path.read_text().strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    path.chmod(0o600)
    return key
