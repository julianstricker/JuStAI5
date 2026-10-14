"""Device records (database) incl. encrypted credential handling."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from justai.common.errors import NotFound, ValidationFailed
from justai.db.engine import Database
from justai.db.models import Device
from justai.system.store import SecretStore


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    driver_id: str
    room_id: str | None = None
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    fingerprint: str | None = None


class DevicePatch(BaseModel):
    name: str | None = None
    room_id: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None


def _secret_key(device_id: str, field: str) -> str:
    return f"device:{device_id}:{field}"


class DeviceService:
    def __init__(self, db: Database, secrets: SecretStore) -> None:
        self.db = db
        self.secrets = secrets

    async def list(self, room_id: str | None = None) -> list[Device]:
        stmt = select(Device).order_by(Device.name)
        if room_id:
            stmt = stmt.where(Device.room_id == room_id)
        async with self.db.session() as s:
            return list((await s.scalars(stmt)).all())

    async def get(self, device_id: str) -> Device:
        async with self.db.session() as s:
            device = await s.get(Device, device_id)
        if device is None:
            raise NotFound(f"device {device_id} not found")
        return device

    async def create(self, data: DeviceIn, secret_fields: list[str]) -> Device:
        public, secret = _split(data.config, secret_fields)
        async with self.db.session() as s:
            device = Device(name=data.name, driver_id=data.driver_id, room_id=data.room_id,
                            enabled=data.enabled, config=public, settings=data.settings,
                            fingerprint=data.fingerprint)
            s.add(device)
            await s.flush()
            device_id = device.id
        for k, v in secret.items():
            await self.secrets.set(_secret_key(device_id, k), str(v))
        return device

    async def update(self, device_id: str, patch: DevicePatch, secret_fields: list[str]) -> Device:
        secret: dict[str, Any] = {}
        async with self.db.session() as s:
            device = await s.get(Device, device_id)
            if device is None:
                raise NotFound(f"device {device_id} not found")
            if patch.name is not None:
                device.name = patch.name
            if "room_id" in patch.model_fields_set:
                device.room_id = patch.room_id
            if patch.enabled is not None:
                device.enabled = patch.enabled
            if patch.config is not None:
                public, secret = _split(patch.config, secret_fields)
                device.config = {**device.config, **public}
            if patch.settings is not None:
                device.settings = {**device.settings, **patch.settings}
        for k, v in secret.items():
            if v in (None, ""):
                continue  # empty secret field in a form means "keep the stored value"
            await self.secrets.set(_secret_key(device_id, k), str(v))
        return await self.get(device_id)

    async def delete(self, device_id: str) -> None:
        async with self.db.session() as s:
            device = await s.get(Device, device_id)
            if device is None:
                raise NotFound(f"device {device_id} not found")
            await s.delete(device)
        await self.secrets.delete_prefix(f"device:{device_id}:")

    async def full_config(self, device: Device) -> dict[str, Any]:
        """Config including decrypted secrets (only for drivers, never for the API)."""
        secret = await self.secrets.get_many(f"device:{device.id}:")
        return {**device.config, **secret}

    async def secret_fields_present(self, device_id: str) -> list[str]:
        return sorted((await self.secrets.get_many(f"device:{device_id}:")).keys())

    async def set_status(self, device_id: str, *, status: str, detail: str | None = None,
                         capabilities: list[str] | None = None,
                         info: dict[str, Any] | None = None, seen: bool = False) -> None:
        from datetime import UTC, datetime

        async with self.db.session() as s:
            device = await s.get(Device, device_id)
            if device is None:
                return
            device.status = status
            device.status_detail = detail
            if capabilities is not None:
                device.capabilities = sorted(capabilities)
            if info is not None:
                device.info = info
            if seen:
                device.last_seen_at = datetime.now(UTC)


def _split(config: dict[str, Any], secret_fields: list[str]) -> tuple[dict[str, Any], dict[str, Any]]:
    public = {k: v for k, v in config.items() if k not in secret_fields}
    secret = {k: v for k, v in config.items() if k in secret_fields}
    for key, value in public.items():
        if isinstance(value, str) and "://" in value and "@" in value.split("://", 1)[1]:
            raise ValidationFailed(f"config field '{key}' contains credentials; use a secret field")
    return public, secret
