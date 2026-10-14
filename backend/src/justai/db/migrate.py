"""Apply database migrations at startup (guarded by an advisory lock)."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import Connection

from justai.db.engine import Database
from justai.logging import get_logger

log = get_logger(__name__)
_MIGRATION_LOCK_ID = 5_000_501


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    return cfg


async def upgrade_to_head(db: Database) -> None:
    async with db.engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    async with db.engine.connect() as conn:
        await conn.execute(text(f"SELECT pg_advisory_lock({_MIGRATION_LOCK_ID})"))
        try:

            def _run(sync_conn: Connection) -> None:
                cfg = _alembic_config()
                cfg.attributes["connection"] = sync_conn
                command.upgrade(cfg, "head")

            await conn.run_sync(_run)
            await conn.commit()
        finally:
            await conn.execute(text(f"SELECT pg_advisory_unlock({_MIGRATION_LOCK_ID})"))
            await conn.commit()
    log.info("database schema up to date")
