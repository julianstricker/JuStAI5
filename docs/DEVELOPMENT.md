# Development

*[Deutsch](de/DEVELOPMENT.md) · English*

## Requirements

* Linux x86_64 (workspace resolution is limited to `sys_platform == 'linux'` because
  `tflite-runtime` for openWakeWord only exists there – see the override in
  `pyproject.toml`)
* [uv](https://docs.astral.sh/uv/) ≥ 0.5, Python 3.12 (uv installs it if needed)
* Node 22 for the frontend
* Docker with Compose v2 for the full stack and the E2E tests
* ffmpeg (only for local runs outside Docker)

## Setup

```bash
uv sync --all-packages          # backend, SDK, sandbox + dev tools in .venv
cd frontend && npm ci           # frontend dependencies
```

Models for local audio tests and local operation without Docker:

```bash
uv run python scripts/fetch_models.py ./.models
export JUSTAI_TEST_MODELS_DIR=$PWD/.models
```

## Development mode with Docker (recommended)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

* Backend, SDK and plugins are mounted read-only into the container,
  `JUSTAI_ENV=development` enables Uvicorn reload.
* Vite dev server on <http://localhost:5173> (proxy to the core).

## Core locally without Docker

Needs a reachable PostgreSQL with pgvector and optionally go2rtc:

```bash
docker run -d --name j5-db -e POSTGRES_USER=justai -e POSTGRES_PASSWORD=dev \
  -e POSTGRES_DB=justai -p 5433:5432 pgvector/pgvector:0.8.1-pg17
export JUSTAI_ENV=development JUSTAI_LOG_JSON=false \
  JUSTAI_DATABASE_URL=postgresql+asyncpg://justai:dev@localhost:5433/justai \
  JUSTAI_DATA_DIR=$PWD/.data JUSTAI_MODELS_DIR=$PWD/.models \
  JUSTAI_BUILTIN_PLUGINS_DIR=$PWD/plugins JUSTAI_STATIC_DIR=$PWD/frontend/dist \
  JUSTAI_SECRET_KEY_FILE=$PWD/.data/master_key JUSTAI_DATABASE_PASSWORD_FILE=/nonexistent \
  JUSTAI_GO2RTC_URL=http://localhost:1984 JUSTAI_GO2RTC_RTSP_URL=rtsp://localhost:8554
uv run python -m justai.main
```

All variables: `backend/src/justai/config.py` (prefix `JUSTAI_`).

## Code quality

```bash
uv run ruff check .              # lint (rules in pyproject.toml, line length 120)
uv run ruff format --check .
(cd backend && uv run mypy src)  # strict, with the pydantic plugin
(cd sdk/python && uv run mypy src)
(cd sandbox && uv run mypy src)
cd frontend && npm run lint && npm run typecheck
```

Conventions:

* New dependencies only with a reason (the lockfile is committed).
* Write domain logic without I/O where possible (e.g. `ptz/tracking.py`,
  `audio/arbitration.py`, `output/router.py`) so it can be tested without
  infrastructure.
* Never start background tasks with a bare `asyncio.create_task`, but with
  `justai.common.tasks.spawn` or the `Supervisor`.
* Code, comments, logs, tool descriptions, tool results and error messages are English.
  The language model answers in the language of the conversation.
* Texts spoken or stored without the model go into `justai/i18n.py` with English,
  German and Italian versions.
* Interface texts go into `frontend/src/shared/i18n/en.ts` and are translated in `de.ts`
  and `it.ts`; the build fails if a key is missing. In components use `const t = useT()`,
  outside of components `tg()`.
* Never log secrets: `justai.common.redact` filters known keys. Plugin secrets are
  declared by the manifest in `secret_fields`.

## Database migrations

```bash
cd backend
uv run alembic revision -m "description"     # file in src/justai/db/migrations/versions/
```

Migrations run automatically at core start. Every migration must work on an existing
database (no recreating of data needed).

## Adding a new domain module

1. Package under `backend/src/justai/<module>/` with a service (logic) and
   `extension.py` (`start()`, `stop()`, `register_tools(registry)`).
2. Instantiate it in `extensions.py`.
3. API routes in `api/routes/ext_<module>.py`, registered in `api/app.py`.
4. Add event types to the catalog (`events/catalog.py`).
5. Unit tests for the pure logic, an E2E test if useful.

## A new plugin

See [PLUGINS.md](PLUGINS.md). In short: a folder under `plugins/` with `plugin.yaml` and
`plugin.py`, tests with `justai_sdk.testing.FakePluginContext`.

## Tests

See [TESTING.md](TESTING.md).
