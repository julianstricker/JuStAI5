# 0003 – PostgreSQL + pgvector als einzige Datenbank

**Status:** angenommen

## Kontext

Benötigt werden relationale Daten (Räume, Geräte, Benutzer, Automationen),
flexible Dokumente (Konfiguration, Event-Payloads), eine dauerhafte Job-Queue und
Vektorsuche (Gedächtnis, Gesichter).

## Entscheidung

PostgreSQL 17 mit pgvector: Tabellen für Relationen, JSONB für flexible Strukturen,
`vector(384)` für Embeddings, `FOR UPDATE SKIP LOCKED` für die Job-Queue.
SQLAlchemy 2 (async) + Alembic-Migrationen beim Start.

## Alternativen

* **SQLite**: einfacher, aber schwächer bei nebenläufigem Schreiben; Vektorsuche nur
  über Erweiterungen.
* **FerretDB/MongoDB + separate Vektor-DB (Qdrant)**: zusätzliche Dienste, keine
  Transaktionen über Daten und Vektoren hinweg.
* **Redis für die Queue**: ein weiterer Dienst ohne echten Mehrwert bei dieser Last.

## Konsequenzen

* Ein Dienst für alles: Backup ist ein `pg_dump` ([DEPLOYMENT.md](../DEPLOYMENT.md)).
* Ein Embedding-Modellwechsel mit anderer Dimension braucht eine Migration und
  Neuberechnung.
