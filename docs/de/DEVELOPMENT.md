# Entwicklung

*Deutsch · [English](../DEVELOPMENT.md)*

## Voraussetzungen

* Linux x86_64 (die Workspace-Auflösung ist auf `sys_platform == 'linux'` beschränkt,
  weil `tflite-runtime` für openWakeWord nur dort existiert – siehe Override in
  `pyproject.toml`)
* [uv](https://docs.astral.sh/uv/) ≥ 0.5, Python 3.12 (uv installiert es bei Bedarf)
* Node 22 für das Frontend
* Docker mit Compose v2 für den vollständigen Stack und die E2E-Tests
* ffmpeg (nur für lokale Läufe außerhalb von Docker)

## Setup

```bash
uv sync --all-packages          # Backend, SDK, Sandbox + Dev-Werkzeuge in .venv
cd frontend && npm ci           # Frontend-Abhängigkeiten
```

Modelle für lokale Audio-Tests und lokalen Betrieb ohne Docker:

```bash
uv run python scripts/fetch_models.py ./.models
export JUSTAI_TEST_MODELS_DIR=$PWD/.models
```

## Entwicklungsmodus mit Docker (empfohlen)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

* Backend, SDK und Plugins werden read-only in den Container gemountet,
  `JUSTAI_ENV=development` aktiviert Uvicorn-Reload.
* Vite-Dev-Server auf <http://localhost:5173> (Proxy auf den Core).

## Core lokal ohne Docker

Braucht eine erreichbare PostgreSQL mit pgvector und optional go2rtc:

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

Alle Variablen: `backend/src/justai/config.py` (Präfix `JUSTAI_`).

## Codequalität

```bash
uv run ruff check .              # Lint (Regeln in pyproject.toml, Zeilenlänge 120)
uv run ruff format --check .
(cd backend && uv run mypy src)  # strict, mit Pydantic-Plugin
(cd sdk/python && uv run mypy src)
(cd sandbox && uv run mypy src)
cd frontend && npm run lint && npm run typecheck
```

Konventionen:

* Neue Abhängigkeiten nur mit Begründung (Lockfile wird committet).
* Domänenlogik ohne I/O schreiben, wo möglich (z. B. `ptz/tracking.py`,
  `audio/arbitration.py`, `output/router.py`), damit sie ohne Infrastruktur
  testbar ist.
* Hintergrund-Tasks nie mit nacktem `asyncio.create_task` starten, sondern mit
  `justai.common.tasks.spawn` oder dem `Supervisor`.
* Code, Kommentare, Logs, Tool-Beschreibungen, Tool-Ergebnisse und Fehlermeldungen
  sind englisch; das Sprachmodell antwortet in der Sprache des Gesprächs.
* Texte, die ohne Modell gesprochen oder gespeichert werden, kommen nach
  `justai/i18n.py` (Englisch, Deutsch, Italienisch).
* Oberflächentexte kommen nach `frontend/src/shared/i18n/en.ts` und werden in `de.ts`
  und `it.ts` übersetzt; fehlt ein Schlüssel, bricht der Build. In Komponenten
  `const t = useT()`, außerhalb `tg()`.
* Secrets nie loggen: `justai.common.redact` filtert bekannte Schlüssel. Plugin-
  Secrets deklariert das Manifest in `secret_fields`.

## Datenbankmigrationen

```bash
cd backend
uv run alembic revision -m "beschreibung"     # Datei in src/justai/db/migrations/versions/
```

Migrationen laufen beim Start des Core automatisch. Jede Migration muss auf einer
bestehenden Datenbank funktionieren (kein Neuanlegen von Daten nötig).

## Ein neues Fachmodul anlegen

1. Paket unter `backend/src/justai/<modul>/` mit Service (Logik) und
   `extension.py` (`start()`, `stop()`, `register_tools(registry)`).
2. In `extensions.py` instanziieren.
3. API-Routen in `api/routes/ext_<modul>.py`, in `api/app.py` registrieren.
4. Event-Typen im Katalog (`events/catalog.py`) ergänzen.
5. Unit-Tests für die reine Logik, ggf. E2E-Test.

## Ein neues Plugin

Siehe [PLUGINS.md](PLUGINS.md). Kurz: Ordner unter `plugins/` mit `plugin.yaml`
und `plugin.py`, Tests mit `justai_sdk.testing.FakePluginContext`.

## Tests

Siehe [TESTING.md](TESTING.md).
