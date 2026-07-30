#!/usr/bin/env bash
# Nightly Postgres backup for EvampOps.
# Retention: 7 daily dumps + 1 monthly dump under ./backups/
#
# Usage (from repo root or any cwd):
#   bash scripts/backup-postgres.sh
#
# Restore example:
#   docker compose exec -T postgres pg_restore -U evamp -d evamp_ops --clean --if-exists \
#     < backups/daily/evamp_ops_YYYY-MM-DD.dump
# (Prefer restore into a fresh DB / stop writers first. Adjust -U/-d from .env.)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DAILY_DIR="$ROOT/backups/daily"
MONTHLY_DIR="$ROOT/backups/monthly"
LOG_DIR="$ROOT/backups/logs"
KEEP_DAILY=7
KEEP_MONTHLY=1

mkdir -p "$DAILY_DIR" "$MONTHLY_DIR" "$LOG_DIR"

# Load DB_* from .env if present (compose uses the same).
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

DB_USER="${DB_USER:-evamp}"
DB_NAME="${POSTGRES_DB:-${DB_NAME:-evamp_ops}}"

TODAY="$(date +%Y-%m-%d)"
MONTH="$(date +%Y-%m)"
DAILY_FILE="$DAILY_DIR/evamp_ops_${TODAY}.dump"
MONTHLY_FILE="$MONTHLY_DIR/evamp_ops_${MONTH}.dump"
LOG_FILE="$LOG_DIR/backup.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

if ! docker compose ps --status running --services 2>/dev/null | grep -qx postgres; then
  log "ERROR: postgres container is not running (docker compose up -d postgres)"
  exit 1
fi

log "Starting backup → $DAILY_FILE"
docker compose exec -T postgres \
  pg_dump -U "$DB_USER" -d "$DB_NAME" -Fc --no-owner --no-acl \
  > "$DAILY_FILE.tmp"
mv -f "$DAILY_FILE.tmp" "$DAILY_FILE"
SIZE="$(du -h "$DAILY_FILE" | awk '{print $1}')"
log "Daily backup OK ($SIZE)"

# One monthly snapshot per calendar month (first successful run that month).
# Retention keeps only the newest monthly file.
if [[ ! -f "$MONTHLY_FILE" ]]; then
  cp -f "$DAILY_FILE" "$MONTHLY_FILE"
  log "Monthly snapshot created → $MONTHLY_FILE"
else
  log "Monthly snapshot already exists for $MONTH (unchanged)"
fi

# Retention: newest N by filename (YYYY-MM-DD / YYYY-MM sorts lexicographically).
prune_keep_newest() {
  local dir="$1"
  local pattern="$2"
  local keep="$3"
  local -a files=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && files+=("$f")
  done < <(ls -1 "$dir"/$pattern 2>/dev/null | sort -r)
  local i=0
  for f in "${files[@]}"; do
    i=$((i + 1))
    if (( i > keep )); then
      log "Prune $f"
      rm -f "$f"
    fi
  done
}

prune_keep_newest "$DAILY_DIR" "evamp_ops_????-??-??.dump" "$KEEP_DAILY"
prune_keep_newest "$MONTHLY_DIR" "evamp_ops_????-??.dump" "$KEEP_MONTHLY"

log "Done. Daily kept=$KEEP_DAILY Monthly kept=$KEEP_MONTHLY"
