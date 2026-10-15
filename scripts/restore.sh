#!/usr/bin/env bash
# Restore a backup created by backup.sh. Stops the core while restoring.
# Usage: ./scripts/restore.sh backups/justai5-backup-XXXX.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."
# Volume names follow the compose project (default "justai5", see docker-compose.yml).
PROJECT="${COMPOSE_PROJECT_NAME:-justai5}"
ARCHIVE="$1"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
tar xzf "$ARCHIVE" -C "$WORK"
docker compose stop core sandbox || true
for vol in secrets data; do
  docker volume create "${PROJECT}_${vol}" >/dev/null
  docker run --rm -v "${PROJECT}_${vol}:/v" -v "$WORK:/in:ro" alpine:3.22 \
    sh -c "find /v -mindepth 1 -delete && tar xzf /in/${vol}.tar.gz -C /v"
done
docker compose up -d postgres
until docker compose exec -T postgres pg_isready -U justai -d justai >/dev/null 2>&1; do sleep 1; done
docker compose exec -T postgres psql -U justai -d postgres -c "DROP DATABASE IF EXISTS justai WITH (FORCE)" -c "CREATE DATABASE justai OWNER justai"
docker compose exec -T postgres pg_restore -U justai -d justai --no-owner < "$WORK/database.dump"
# The restored secrets may contain a different database password: apply it.
docker compose exec -T postgres sh -c 'psql -U justai -d postgres -c "ALTER USER justai PASSWORD '"'"'$(cat /run/secrets-shared/db_password)'"'"'"' 
docker compose up -d
echo "restore finished"
