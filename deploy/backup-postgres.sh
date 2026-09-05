#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE=${ENV_FILE:-"$ROOT_DIR/deploy/production.env"}
BACKUP_DIR=${BACKUP_DIR:-"$ROOT_DIR/backups"}
RETENTION_DAYS=${RETENTION_DAYS:-14}
STAMP=$(date -u +"%Y%m%dT%H%M%SZ")
TARGET="$BACKUP_DIR/quant-agent-$STAMP.dump"
TEMP="$TARGET.tmp"

umask 077
mkdir -p "$BACKUP_DIR"
trap 'rm -f "$TEMP"' EXIT HUP INT TERM

docker compose \
  --env-file "$ENV_FILE" \
  -f "$ROOT_DIR/docker-compose.production.yml" \
  exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "$TEMP"

test -s "$TEMP"
docker compose \
  --env-file "$ENV_FILE" \
  -f "$ROOT_DIR/docker-compose.production.yml" \
  exec -T postgres pg_restore --list \
  < "$TEMP" \
  > /dev/null

mv "$TEMP" "$TARGET"
sha256sum "$TARGET" > "$TARGET.sha256"
trap - EXIT HUP INT TERM

python3 - "$BACKUP_DIR" "$RETENTION_DAYS" <<'PY'
from pathlib import Path
import sys
import time

directory = Path(sys.argv[1])
cutoff = time.time() - int(sys.argv[2]) * 86400
for path in directory.glob("quant-agent-*.dump"):
    if path.stat().st_mtime < cutoff:
        path.unlink()
        checksum = path.with_suffix(path.suffix + ".sha256")
        checksum.unlink(missing_ok=True)
PY

echo "$TARGET"
