#!/usr/bin/env bash
# Weekly restore drill — prove juli-pre-migrate-*.dump backups are restorable.
#
# VPS-local only (ADR-027): the backup file never leaves this host. Intended for
# systemd timer juli-restore-drill.timer; logs a single pass/fail line for journalctl.
#
# Env overrides (match safe-alembic-upgrade.sh where applicable):
#   RELEASE_DIR           — repo root with alembic.ini / .venv (required)
#   API_ENV_FILE          — env file with DATABASE_URL (default /etc/juli/api.env)
#   BACKUP_DIR            — backup source directory (default ~/backups)
#   VENV_PYTHON           — python for helpers (default ${RELEASE_DIR}/.venv/bin/python)
#   SCRATCH_DB_PREFIX     — scratch database name prefix (default juli_restore_drill_)
#
# The latest backup filename is resolved once at drill start so BACKUP_RETENTION_DAYS
# rotation in safe-alembic-upgrade.sh cannot delete the file mid-restore.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="${RELEASE_DIR:-}"
API_ENV_FILE="${API_ENV_FILE:-/etc/juli/api.env}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
SCRATCH_DB_PREFIX="${SCRATCH_DB_PREFIX:-juli_restore_drill_}"

SCRATCH_DB=""
ADMIN_URL=""
SCRATCH_URL=""
DRILL_RESULT="fail"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
    log "FAIL: $*"
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

drop_scratch_db() {
    if [ -z "${SCRATCH_DB}" ] || [ -z "${ADMIN_URL}" ]; then
        return 0
    fi
    log "dropping scratch database ${SCRATCH_DB}"
    psql "${ADMIN_URL}" -v ON_ERROR_STOP=1 -c \
        "DROP DATABASE IF EXISTS \"${SCRATCH_DB}\" WITH (FORCE);" \
        >/dev/null 2>&1 || true
}

cleanup() {
    drop_scratch_db
    if [ "${DRILL_RESULT}" = "pass" ]; then
        log "RESTORE DRILL PASS"
    else
        log "RESTORE DRILL FAIL"
    fi
}
trap cleanup EXIT

if [ -z "${RELEASE_DIR}" ]; then
    fail "RELEASE_DIR must be set to the release worktree root (contains alembic.ini)"
fi
if [ ! -f "${RELEASE_DIR}/alembic.ini" ]; then
    fail "alembic.ini not found under RELEASE_DIR=${RELEASE_DIR}"
fi
if [ ! -f "${API_ENV_FILE}" ]; then
    fail "API env file not found: ${API_ENV_FILE}"
fi

VENV_PYTHON="${VENV_PYTHON:-${RELEASE_DIR}/.venv/bin/python}"
if [ ! -x "${VENV_PYTHON}" ]; then
    fail "Python interpreter not found: ${VENV_PYTHON}"
fi

require_cmd pg_restore
require_cmd psql

set -a
# shellcheck disable=SC1090
source "${API_ENV_FILE}"
set +a

if [ -z "${DATABASE_URL:-}" ] && [ -z "${DATABASE_DIRECT_URL:-}" ]; then
    fail "DATABASE_URL or DATABASE_DIRECT_URL must be set in ${API_ENV_FILE}"
fi
if [ -z "${TIKTOK_TOKEN_ENCRYPTION_KEY:-}" ]; then
    log "WARN: TIKTOK_TOKEN_ENCRYPTION_KEY is unset — token decrypt check will fail if credentials exist"
fi

export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"
HELPER=( "${VENV_PYTHON}" "${SCRIPT_DIR}/safe_alembic_helpers.py" )

log "restore-drill starting (RELEASE_DIR=${RELEASE_DIR}, BACKUP_DIR=${BACKUP_DIR})"

BACKUP_FILE="$("${HELPER[@]}" latest-backup --backup-dir "${BACKUP_DIR}")" \
    || fail "could not resolve latest backup in ${BACKUP_DIR}"
if [ ! -f "${BACKUP_FILE}" ]; then
    fail "resolved backup file missing: ${BACKUP_FILE}"
fi
BACKUP_SIZE="$(wc -c < "${BACKUP_FILE}" | tr -d ' ')"
log "using backup (resolved once at drill start): ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"

MIGRATION_URL="$("${HELPER[@]}" migration-db-url)"
ADMIN_URL="$("${HELPER[@]}" admin-db-url)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SCRATCH_DB="${SCRATCH_DB_PREFIX}${TS}_$$"
SCRATCH_URL="$("${HELPER[@]}" database-url-with-name --database "${SCRATCH_DB}")"

log "creating scratch database ${SCRATCH_DB} on same Postgres instance"
if ! psql "${ADMIN_URL}" -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"${SCRATCH_DB}\""; then
    fail "could not create scratch database ${SCRATCH_DB}"
fi

log "pg_restore into scratch database ${SCRATCH_DB}"
if ! pg_restore --no-owner --no-acl -d "${SCRATCH_URL}" "${BACKUP_FILE}"; then
    fail "pg_restore failed for ${BACKUP_FILE}"
fi

log "row-count snapshot against restored copy"
RESTORE_COUNTS="$("${HELPER[@]}" row-counts --url "${SCRATCH_URL}")" \
    || fail "row-count check failed against restored database"
log "restored row counts: ${RESTORE_COUNTS}"

set +e
DECRYPT_JSON="$("${HELPER[@]}" verify-token-decrypt --url "${SCRATCH_URL}" 2>&1)"
DECRYPT_EXIT=$?
set -e
if [ "${DECRYPT_EXIT}" -ne 0 ]; then
    log "FAIL: tiktok_credentials decrypt check failed on restored copy: ${DECRYPT_JSON}"
    fail "token decrypt verification failed after restore"
fi
log "token decrypt check on restored copy: ${DECRYPT_JSON}"

DRILL_RESULT="pass"
log "restore-drill verification succeeded for ${BACKUP_FILE}"
exit 0
