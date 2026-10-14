"""User accounts, password hashing (argon2id) and JWT session tokens."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from sqlalchemy import func, select

from justai.auth.rbac import Role, permissions_for
from justai.common.errors import Conflict, NotFound, Unauthorized, ValidationFailed
from justai.db.engine import Database
from justai.db.models import User
from justai.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    role: str
    permissions: frozenset[str]
    person_id: str | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == Role.ADMIN

    @property
    def actor(self) -> str:
        return f"user:{self.username}"


class AuthService:
    def __init__(self, db: Database, master_key: str, *, token_ttl_hours: int = 168) -> None:
        self.db = db
        self._hasher = PasswordHasher()
        self._jwt_key = hashlib.sha256(("justai5-jwt:" + master_key).encode()).hexdigest()
        self.token_ttl = timedelta(hours=token_ttl_hours)

    # ----------------------------------------------------------------- bootstrap
    async def ensure_admin(self, username: str, password: str | None, data_dir: Path) -> None:
        """Create the first admin account. A random password is written to a file."""
        async with self.db.session() as s:
            count = await s.scalar(select(func.count()).select_from(User))
        if count:
            return
        generated = password is None
        password = password or secrets.token_urlsafe(12)
        await self.create_user(username, password, Role.ADMIN, display_name="Administrator")
        if generated:
            target = data_dir / "initial_admin_password.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"username: {username}\npassword: {password}\n")
            target.chmod(0o600)
            log.warning("initial admin account created; password stored in file",
                        username=username, file=str(target))

    # ---------------------------------------------------------------------- users
    async def create_user(self, username: str, password: str, role: Role | str,
                          display_name: str = "", person_id: str | None = None) -> User:
        if len(password) < 8:
            raise ValidationFailed("password must have at least 8 characters")
        role = Role(role)
        async with self.db.session() as s:
            exists = await s.scalar(select(User).where(User.username == username))
            if exists:
                raise Conflict(f"user {username} exists")
            user = User(username=username, password_hash=self._hasher.hash(password),
                        role=role, display_name=display_name or username, person_id=person_id)
            s.add(user)
        return user

    async def list_users(self) -> list[User]:
        async with self.db.session() as s:
            return list((await s.scalars(select(User).order_by(User.username))).all())

    async def update_user(self, user_id: str, *, role: str | None = None,
                          display_name: str | None = None, disabled: bool | None = None,
                          password: str | None = None, person_id: str | None = None) -> User:
        async with self.db.session() as s:
            user = await s.get(User, user_id)
            if user is None:
                raise NotFound("user not found")
            if role is not None:
                user.role = Role(role)
            if display_name is not None:
                user.display_name = display_name
            if disabled is not None:
                user.disabled = disabled
                user.token_version += 1
            if person_id is not None:
                user.person_id = person_id or None
            if password is not None:
                if len(password) < 8:
                    raise ValidationFailed("password must have at least 8 characters")
                user.password_hash = self._hasher.hash(password)
                user.token_version += 1
            return user

    async def delete_user(self, user_id: str) -> None:
        async with self.db.session() as s:
            user = await s.get(User, user_id)
            if user is None:
                raise NotFound("user not found")
            await s.delete(user)

    # --------------------------------------------------------------------- tokens
    async def login(self, username: str, password: str) -> tuple[str, Principal]:
        async with self.db.session() as s:
            user = await s.scalar(select(User).where(User.username == username))
            if user is None or user.disabled:
                self._hasher.hash(password)  # equalise timing
                raise Unauthorized("invalid credentials")
            try:
                self._hasher.verify(user.password_hash, password)
            except (VerifyMismatchError, InvalidHashError) as exc:
                raise Unauthorized("invalid credentials") from exc
            if self._hasher.check_needs_rehash(user.password_hash):
                user.password_hash = self._hasher.hash(password)
            user.last_login_at = datetime.now(UTC)
            principal = self._principal(user)
            token = self._issue(user)
        return token, principal

    async def logout_everywhere(self, user_id: str) -> None:
        async with self.db.session() as s:
            user = await s.get(User, user_id)
            if user:
                user.token_version += 1

    def _issue(self, user: User) -> str:
        now = datetime.now(UTC)
        claims = {"sub": user.id, "ver": user.token_version, "iat": now, "exp": now + self.token_ttl}
        return jwt.encode(claims, self._jwt_key, algorithm="HS256")

    async def authenticate(self, token: str) -> Principal:
        try:
            claims = jwt.decode(token, self._jwt_key, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise Unauthorized("invalid token") from exc
        async with self.db.session() as s:
            user = await s.get(User, claims.get("sub"))
        if user is None or user.disabled or user.token_version != claims.get("ver"):
            raise Unauthorized("session expired")
        return self._principal(user)

    def issue_scoped_token(self, subject: str, scope: str, ttl: timedelta) -> str:
        """Short-lived token for non-user principals (display clients, media URLs)."""
        now = datetime.now(UTC)
        claims = {"sub": subject, "scope": scope, "iat": now, "exp": now + ttl}
        return jwt.encode(claims, self._jwt_key, algorithm="HS256")

    def verify_scoped_token(self, token: str, scope: str) -> str:
        try:
            claims = jwt.decode(token, self._jwt_key, algorithms=["HS256"])
        except jwt.PyJWTError as exc:
            raise Unauthorized("invalid token") from exc
        if claims.get("scope") != scope:
            raise Unauthorized("wrong token scope")
        return str(claims["sub"])

    @staticmethod
    def _principal(user: User) -> Principal:
        return Principal(user_id=user.id, username=user.username, role=user.role,
                         permissions=permissions_for(user.role), person_id=user.person_id)
