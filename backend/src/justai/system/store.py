"""Settings, encrypted secrets and the audit log."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from justai.common.crypto import SecretBox
from justai.common.redact import redact
from justai.db.engine import Database
from justai.db.models import AuditEntry, Secret, Setting

M = TypeVar("M", bound=BaseModel)


class SettingsStore:
    """Key/value JSON settings with an in-memory cache."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[str, Any] = {}

    async def get(self, key: str, default: Any = None) -> Any:
        if key in self._cache:
            return self._cache[key]
        async with self.db.session() as s:
            row = await s.get(Setting, key)
        value = row.value if row else default
        if row:
            self._cache[key] = value
        return value

    async def get_model(self, key: str, model: type[M]) -> M:
        raw = await self.get(key)
        return model.model_validate(raw or {})

    async def set(self, key: str, value: Any) -> None:
        if isinstance(value, BaseModel):
            value = value.model_dump(mode="json")
        async with self.db.session() as s:
            stmt = insert(Setting).values(key=key, value=value)
            await s.execute(stmt.on_conflict_do_update(index_elements=[Setting.key],
                                                       set_={"value": value}))
        self._cache[key] = value


class SecretStore:
    """Encrypted secrets (API keys, device credentials). Values never leave via the API."""

    def __init__(self, db: Database, box: SecretBox) -> None:
        self.db = db
        self.box = box

    async def get(self, key: str) -> str | None:
        async with self.db.session() as s:
            row = await s.get(Secret, key)
        return self.box.decrypt(row.ciphertext) if row else None

    async def get_many(self, prefix: str) -> dict[str, str]:
        async with self.db.session() as s:
            rows = (await s.scalars(select(Secret).where(Secret.key.startswith(prefix)))).all()
        return {r.key[len(prefix):]: self.box.decrypt(r.ciphertext) for r in rows}

    async def set(self, key: str, value: str) -> None:
        ct = self.box.encrypt(value)
        async with self.db.session() as s:
            stmt = insert(Secret).values(key=key, ciphertext=ct)
            await s.execute(stmt.on_conflict_do_update(index_elements=[Secret.key],
                                                       set_={"ciphertext": ct}))

    async def delete(self, key: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(Secret).where(Secret.key == key))

    async def delete_prefix(self, prefix: str) -> None:
        async with self.db.session() as s:
            await s.execute(delete(Secret).where(Secret.key.startswith(prefix)))

    async def has(self, key: str) -> bool:
        async with self.db.session() as s:
            return (await s.get(Secret, key)) is not None


class AuditLog:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def record(self, actor: str, action: str, target: str | None = None,
                     **detail: Any) -> None:
        async with self.db.session() as s:
            s.add(AuditEntry(actor=actor, action=action, target=target, detail=redact(detail)))

    async def list(self, limit: int = 100, action_prefix: str | None = None) -> list[AuditEntry]:
        stmt = select(AuditEntry).order_by(AuditEntry.ts.desc()).limit(limit)
        if action_prefix:
            stmt = stmt.where(AuditEntry.action.startswith(action_prefix))
        async with self.db.session() as s:
            return list((await s.scalars(stmt)).all())
