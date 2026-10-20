# 0003 – PostgreSQL + pgvector as the only database

*[Deutsch](../de/adr/0003-postgres-pgvector.md) · English*

**Status:** accepted

## Context

Needed are relational data (rooms, devices, users, automations), flexible documents
(configuration, event payloads), a durable job queue and vector search (memory, faces).

## Decision

PostgreSQL 17 with pgvector: tables for relations, JSONB for flexible structures,
`vector(384)` for embeddings, `FOR UPDATE SKIP LOCKED` for the job queue. SQLAlchemy 2
(async) + Alembic migrations at start.

## Alternatives

* **SQLite**: simpler, but weaker with concurrent writes; vector search only through
  extensions.
* **FerretDB/MongoDB + separate vector DB (Qdrant)**: additional services, no transactions
  across data and vectors.
* **Redis for the queue**: another service without real benefit at this load.

## Consequences

* One service for everything: a backup is one `pg_dump` ([DEPLOYMENT.md](../DEPLOYMENT.md)).
* Changing the embedding model to another dimension needs a migration and recalculation.
