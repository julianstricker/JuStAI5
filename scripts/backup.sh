#!/usr/bin/env bash
# Full backup: database dump, data volume (plugins, keys, files) and secrets volume.
# Usage: ./scripts/backup.sh [target-dir]
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$TARGET"
echo "dumping database ..."
docker compose exec -T postgres pg_dump -U justai -d justai --format=custom > "$WORK/database.dump"
echo "archiving volumes ..."
for vol in data secrets; do
  docker run --rm -v "justai5_${vol}:/v:ro" -v "$WORK:/out" alpine:3.22 tar czf "/out/${vol}.tar.gz" -C /v .
done
cp docker-compose.yml "$WORK/"
[ -f .env ] && cp .env "$WORK/env"
tar czf "$TARGET/justai5-backup-$STAMP.tar.gz" -C "$WORK" .
chmod 600 "$TARGET/justai5-backup-$STAMP.tar.gz"
echo "backup written to $TARGET/justai5-backup-$STAMP.tar.gz (contains secrets - store safely)"
