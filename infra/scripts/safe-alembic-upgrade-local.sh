#!/usr/bin/env bash
# Local-dev wrapper for `alembic upgrade head` with DB-identity confirmation,
# pre-migration backup, row-count snapshots, and post-migration verification.
#
# Loads DATABASE_URL from the repo-root .env (same convention as backend local dev).
# Production deploys use infra/scripts/safe-alembic-upgrade.sh instead.
#
# Usage:
#   ./infra/scripts/safe-alembic-upgrade-local.sh [--yes]
#
# Env overrides:
#   RELEASE_DIR           — repo root containing alembic.ini (auto-detected)
#   ENV_FILE              — env file with DATABASE_URL (default ${RELEASE_DIR}/.env)
#   BACKUP_DIR            — backup destination (default ~/.juli-backups)
#   BACKUP_RETENTION_DAYS — delete backups older than N days (default 14)
#   KEEP_BACKUPS          — if set, keep at most this many backups (overrides days)
#   DISK_MARGIN_MB        — extra free-space headroom beyond estimated dump (default 512)
#   VENV_PYTHON           — python for helpers (default ${RELEASE_DIR}/.venv/bin/python)
#   SAFE_MIGRATE_YES      — set to 1 to skip interactive confirmation (same as --yes)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RELEASE_DIR="${RELEASE_DIR:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
ENV_FILE="${ENV_FILE:-${RELEASE_DIR}/.env}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/.juli-backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
DISK_MARGIN_MB="${DISK_MARGIN_MB:-512}"
ALLOWLIST_FILE="${SCRIPT_DIR}/safe-migrate-allowlist.txt"
MIGRATIONS_DIR="${MIGRATIONS_DIR:-}"
AUTO_YES=false

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

usage() {
    cat <<EOF
Usage: $(basename "$0") [--yes]

Run alembic upgrade head locally with pg_dump backup and row-count verification.

  --yes    Skip interactive DB-identity confirmation (or set SAFE_MIGRATE_YES=1)

When stdin is not a TTY and --yes is not set, the script exits with an actionable
error instead of blocking on a prompt.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --yes)
            AUTO_YES=true
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "unknown argument: $1 (try --help)"
            ;;
    esac
    shift
done

if [ "${SAFE_MIGRATE_YES:-}" = "1" ]; then
    AUTO_YES=true
fi

if [ ! -f "${RELEASE_DIR}/alembic.ini" ]; then
    fail "alembic.ini not found under RELEASE_DIR=${RELEASE_DIR}"
fi
if [ ! -f "${ENV_FILE}" ]; then
    fail "env file not found: ${ENV_FILE} (copy .env.example to .env and fill DATABASE_URL)"
fi

VENV_PYTHON="${VENV_PYTHON:-${RELEASE_DIR}/.venv/bin/python}"
if [ ! -x "${VENV_PYTHON}" ]; then
    if command -v python3 >/dev/null 2>&1; then
        VENV_PYTHON="$(command -v python3)"
    else
        fail "Python interpreter not found: set VENV_PYTHON or create ${RELEASE_DIR}/.venv"
    fi
fi

if [ -z "${MIGRATIONS_DIR}" ]; then
    MIGRATIONS_DIR="${RELEASE_DIR}/backend/src/juli_backend/database/migrations/versions"
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

if [ -z "${DATABASE_URL:-}" ] && [ -z "${DATABASE_DIRECT_URL:-}" ]; then
    fail "DATABASE_URL or DATABASE_DIRECT_URL must be set in ${ENV_FILE}"
fi
if [ -z "${TIKTOK_TOKEN_ENCRYPTION_KEY:-}" ]; then
    log "WARN: TIKTOK_TOKEN_ENCRYPTION_KEY is unset — token decrypt check will fail if credentials exist"
fi

export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"
HELPER=( "${VENV_PYTHON}" "${SCRIPT_DIR}/safe_alembic_helpers.py" )

log "safe-alembic-upgrade-local starting (RELEASE_DIR=${RELEASE_DIR})"

DB_IDENTITY_JSON="$("${HELPER[@]}" db-identity)"
DB_IDENTITY_DISPLAY="$(printf '%s' "${DB_IDENTITY_JSON}" | "${VENV_PYTHON}" -c 'import json,sys; print(json.load(sys.stdin)["display"])')"
log "target database identity: ${DB_IDENTITY_DISPLAY}"

if [ "${AUTO_YES}" != true ]; then
    if [ ! -t 0 ] || [ ! -t 1 ]; then
        fail "Non-interactive session: confirm the target database with --yes or SAFE_MIGRATE_YES=1"
    fi
    printf '\nAbout to migrate: %s\n' "${DB_IDENTITY_DISPLAY}"
    printf 'Type "yes" if this is the right project/database: '
    read -r confirm
    if [ "${confirm}" != "yes" ]; then
        fail "Aborted — confirmation not received (expected \"yes\")"
    fi
fi

require_cmd pg_dump
require_cmd df

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
if [ ! -x "${ALEMBIC}" ]; then
    ALEMBIC="$(command -v alembic || true)"
fi
if [ -z "${ALEMBIC}" ] || [ ! -x "${ALEMBIC}" ]; then
    fail "alembic CLI not found — install backend dev deps or set ALEMBIC_BIN"
fi

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
    log "POST-MIGRATION REGRESSION DETECTED — migration aborted"
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

log "safe-alembic-upgrade-local complete"
