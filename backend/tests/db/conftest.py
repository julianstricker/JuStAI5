"""Fixtures for tests against a real PostgreSQL with pgvector.

Set JUSTAI_TEST_DATABASE_URL, e.g.
postgresql+asyncpg://justai:<pw>@127.0.0.1:55432/justai_test - the schema is migrated
to head; tests clean up the rows they create.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest

from justai.db.engine import Database
from justai.db.migrate import upgrade_to_head

pytestmark = pytest.mark.db


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    url = os.environ.get("JUSTAI_TEST_DATABASE_URL")
    if not url:
        pytest.skip("JUSTAI_TEST_DATABASE_URL not set")
    database = Database(url, pool_size=2)
    await upgrade_to_head(database)
    yield database
    await database.engine.dispose()
