"""Process configuration (environment variables).

Only bootstrap settings live here. Everything a user configures at runtime (rooms,
devices, AI providers, plugin settings) is stored in the database and managed via
the admin UI.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JUSTAI_", env_file=None, extra="ignore")

    env: str = "production"  # production | development | test
    host: str = "0.0.0.0"
    port: int = 8080
    public_url: str = "http://localhost:8080"
    log_level: str = "INFO"
    log_json: bool = True

    database_url: str = "postgresql+asyncpg://justai@postgres:5432/justai"
    database_password_file: Path | None = Path("/run/secrets-shared/db_password")
    database_password: SecretStr | None = None

    data_dir: Path = Path("/data")
    models_dir: Path = Path("/models")
    builtin_plugins_dir: Path = Path("/app/plugins")
    static_dir: Path = Path("/app/static")

    secret_key_file: Path = Path("/run/secrets-shared/master_key")
    secret_key: SecretStr | None = None

    admin_username: str = "admin"
    admin_password: SecretStr | None = None
    jwt_ttl_hours: int = 24 * 7

    go2rtc_url: str = "http://go2rtc:1984"
    go2rtc_rtsp_url: str = "rtsp://go2rtc:8554"
    # How go2rtc reaches the core (to pull live talkback audio).
    core_internal_url: str = "http://core:8080"

    sandbox_url: str = "http://sandbox:8090"
    sandbox_token_file: Path = Path("/run/secrets-shared/sandbox_token")

    discovery_default_cidrs: list[str] = Field(default_factory=list)
    cors_origins: list[str] = Field(default_factory=list)
    enable_simulated_devices: bool = True

    @property
    def is_dev(self) -> bool:
        return self.env == "development"

    def resolved_database_url(self) -> str:
        """Insert the password from the secret file into the database URL if needed."""
        password: str | None = None
        if self.database_password is not None:
            password = self.database_password.get_secret_value()
        elif self.database_password_file and self.database_password_file.exists():
            password = self.database_password_file.read_text().strip()
        url = self.database_url
        if password and "@" in url:
            scheme, rest = url.split("://", 1)
            creds, host = rest.split("@", 1)
            if ":" not in creds:
                from urllib.parse import quote

                url = f"{scheme}://{creds}:{quote(password, safe='')}@{host}"
        return url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
