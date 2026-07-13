#!/usr/bin/env bash
# Wrap `alembic upgrade head` with pre-migration backup, row-count snapshots,
# post-migration verification, and backup rotation.
#
# Intended for deploy-release.sh on the VPS. Requires pg_dump, python3 with
# juli_backend installed (release .venv), and DATABASE_URL in API_ENV_FILE.
#
# Env overrides:
#   RELEASE_DIR           — repo root containing alembic.ini (required)
#   API_ENV_FILE          — env file with DATABASE_URL (default /etc/juli/api.env)
#   BACKUP_DIR            — backup destination (default ~/backups)
#   BACKUP_RETENTION_DAYS — delete backups older than N days (default 14)
#   KEEP_BACKUPS          — if set, keep at most this many backups (overrides days)
#   DISK_MARGIN_MB        — extra free-space headroom beyond estimated dump (default 512)
#   VENV_PYTHON           — python for helpers (default ${RELEASE_DIR}/.venv/bin/python)
#
# Limitation: row-count checks do not detect in-place corruption or partial column
# loss — only net row decreases on protected tables plus one token decrypt sample.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="${RELEASE_DIR:-}"
API_ENV_FILE="${API_ENV_FILE:-/etc/juli/api.env}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
DISK_MARGIN_MB="${DISK_MARGIN_MB:-512}"
ALLOWLIST_FILE="${SCRIPT_DIR}/safe-migrate-allowlist.txt"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-}"

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

if [ -z "${MIGRATIONS_DIR}" ]; then
    MIGRATIONS_DIR="${RELEASE_DIR}/backend/src/juli_backend/database/migrations/versions"
fi

require_cmd pg_dump
require_cmd df

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

log "safe-alembic-upgrade starting (RELEASE_DIR=${RELEASE_DIR})"
log "WARN: deploy does not stop juli-api before migration — concurrent writes can mask or mimic row-count changes"

DB_BYTES="$("${HELPER[@]}" estimate-db-bytes)" || fail "could not estimate database size (check DATABASE_URL connectivity)"
ESTIMATED_DUMP_BYTES=$(( DB_BYTES * 3 / 2 ))
MARGIN_BYTES=$(( DISK_MARGIN_MB * 1024 * 1024 ))
REQUIRED_BYTES=$(( ESTIMATED_DUMP_BYTES + MARGIN_BYTES ))

mkdir -p "${BACKUP_DIR}"
AVAILABLE_KB="$(df -Pk "${BACKUP_DIR}" | awk 'NR==2 {print $4}')"
AVAILABLE_BYTES=$(( AVAILABLE_KB * 1024 ))
log "database size ~$(( DB_BYTES / 1024 / 1024 )) MiB; require ~$(( REQUIRED_BYTES / 1024 / 1024 )) MiB free in ${BACKUP_DIR} (have ~$(( AVAILABLE_BYTES / 1024 / 1024 )) MiB)"
if [ "${AVAILABLE_BYTES}" -lt "${REQUIRED_BYTES}" ]; then
    fail "insufficient disk space in ${BACKUP_DIR}: need ${REQUIRED_BYTES} bytes, have ${AVAILABLE_BYTES} bytes"
fi

FROM_REV="$("${HELPER[@]}" current-revision)"
HEAD_REV="$("${HELPER[@]}" head-revision --alembic-ini "${RELEASE_DIR}/alembic.ini")"
PENDING_JSON="$("${HELPER[@]}" pending-revisions --alembic-ini "${RELEASE_DIR}/alembic.ini" --from-revision "${FROM_REV}")"
log "alembic revision before: ${FROM_REV:-<base>} -> target head: ${HEAD_REV}; pending: ${PENDING_JSON}"

PRE_COUNTS="$("${HELPER[@]}" row-counts)"
log "pre-migration row counts: ${PRE_COUNTS}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
# -Fc (custom format): smaller/faster restore than plain SQL for typical OLTP DBs;
# tradeoff: requires pg_restore instead of psql, not human-readable in an editor.
BACKUP_FILE="${BACKUP_DIR}/juli-pre-migrate-${TS}.dump"
log "starting pg_dump to ${BACKUP_FILE} (-Fc custom format)"

MIGRATION_URL="$("${HELPER[@]}" migration-db-url)"
if ! pg_dump -Fc -f "${BACKUP_FILE}" "${MIGRATION_URL}"; then
    rm -f "${BACKUP_FILE}"
    fail "pg_dump failed — aborting before alembic upgrade"
fi
BACKUP_SIZE="$(wc -c < "${BACKUP_FILE}" | tr -d ' ')"
log "pg_dump complete: ${BACKUP_FILE} (${BACKUP_SIZE} bytes)"

print_restore_command() {
    log "To restore data from this backup (human review required — migration may have partially applied):"
    log "  pg_restore --no-owner --no-acl -d \"\${DATABASE_DIRECT_URL:-\$DATABASE_URL}\" --clean --if-exists \"${BACKUP_FILE}\""
    log "Then reconcile alembic_version manually if the migration partially applied."
}

ALEMBIC="${ALEMBIC_BIN:-${RELEASE_DIR}/.venv/bin/alembic}"

log "running alembic upgrade head"
set +e
MIGRATION_OUTPUT="$(
    cd "${RELEASE_DIR}" && "${ALEMBIC}" upgrade head 2>&1
)"
MIGRATION_EXIT=$?
set -e
printf '%s\n' "${MIGRATION_OUTPUT}"
if [ "${MIGRATION_EXIT}" -ne 0 ]; then
    log "alembic upgrade head failed with exit ${MIGRATION_EXIT}"
    print_restore_command
    fail "alembic upgrade failed — see output above"
fi
log "alembic upgrade head succeeded"

TO_REV="$("${HELPER[@]}" current-revision)"
APPLIED_JSON="$("${HELPER[@]}" pending-revisions --alembic-ini "${RELEASE_DIR}/alembic.ini" --from-revision "${FROM_REV}")"
POST_COUNTS="$("${HELPER[@]}" row-counts)"
log "post-migration row counts: ${POST_COUNTS}"
log "alembic revision after: ${TO_REV}; revisions applied this run: ${APPLIED_JSON}"

REGRESSION=false
REGRESSION_MSG=""
set +e
COMPARE_OUTPUT="$(
    "${VENV_PYTHON}" "${SCRIPT_DIR}/safe_alembic_compare.py" \
        --pre "${PRE_COUNTS}" \
        --post "${POST_COUNTS}" \
        --revisions "${PENDING_JSON}" \
        --allowlist-file "${ALLOWLIST_FILE}" \
        --migrations-dir "${MIGRATIONS_DIR}" 2>&1
)"
COMPARE_EXIT=$?
set -e

if [ "${COMPARE_EXIT}" -eq 2 ]; then
    REGRESSION=true
    REGRESSION_MSG="${COMPARE_OUTPUT}"
elif [ "${COMPARE_EXIT}" -ne 0 ]; then
    fail "row-count comparison failed: ${COMPARE_OUTPUT}"
else
    log "row-count comparison: ${COMPARE_OUTPUT}"
fi

set +e
DECRYPT_JSON="$("${HELPER[@]}" verify-token-decrypt 2>&1)"
DECRYPT_EXIT=$?
set -e
if [ "${DECRYPT_EXIT}" -ne 0 ]; then
    REGRESSION=true
    REGRESSION_MSG="${REGRESSION_MSG}"$'\n'"tiktok_credentials token decrypt failed: ${DECRYPT_JSON}"
    log "FAIL: tiktok_credentials decrypt check failed"
else
    log "token decrypt check: ${DECRYPT_JSON}"
fi

if [ "${REGRESSION}" = true ]; then
    log "POST-MIGRATION REGRESSION DETECTED — deploy must not proceed to service restart"
    printf '%s\n' "${REGRESSION_MSG}"
    print_restore_command
    fail "protected-table regression after migration"
fi

if [ -n "${KEEP_BACKUPS:-}" ]; then
    mapfile -t all_backups < <(ls -1t "${BACKUP_DIR}"/juli-pre-migrate-*.dump 2>/dev/null || true)
    if [ "${#all_backups[@]}" -gt "${KEEP_BACKUPS}" ]; then
        for old in "${all_backups[@]:${KEEP_BACKUPS}}"; do
            log "rotating backup (keep ${KEEP_BACKUPS}): removing ${old}"
            rm -f "${old}"
        done
    fi
else
    while IFS= read -r removed; do
        [ -n "${removed}" ] || continue
        log "rotating backup (older than ${BACKUP_RETENTION_DAYS} days): removed ${removed}"
    done < <(find "${BACKUP_DIR}" -maxdepth 1 -name 'juli-pre-migrate-*.dump' -mtime "+${BACKUP_RETENTION_DAYS}" -print -delete 2>/dev/null || true)
fi

log "safe-alembic-upgrade complete"
