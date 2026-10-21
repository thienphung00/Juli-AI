#!/usr/bin/env bash
# Verified pg_dump of the production database into BACKUP_DIR (P62-A, D72.1).
#
# One script, two callers:
#   - the fast-track deploy workflow's `backup` job (only when the deploy carries a
#     migration, or force_backup), label `fasttrack-<short sha>`;
#   - juli-db-backup.timer, label `daily` — the standing recovery point now that most
#     deploys take no dump at all. The timer fires daily; BACKUP_MIN_INTERVAL_HOURS
#     (72 in the unit) makes it dump only every 3 days.
# safe-alembic-upgrade.sh keeps its own pre-migrate dump (only when a migration is
# pending) because it must sit immediately before `alembic upgrade head`.
#
# VPS-local only (ADR-027): the dump never leaves this host. Runs as the OWNER role
# (verify-migration-privileges): under RLS a runtime-role dump is valid and empty
# (#1575). Files are named juli-pre-migrate-<ts>-<label>.dump so the existing
# rotation and the weekly restore drill (latest-backup) cover them.
#
# A dump earns its final name only after it is verified: non-empty, above a size
# floor, `pg_restore --list` readable, at least MIN_DATA_ENTRIES TABLE DATA entries,
# and data for every table in REQUIRED_TABLES. Then a .sha256 is written beside it
# and old dumps are rotated.
#
# Env overrides:
#   RELEASE_DIR           — release whose .venv + infra/scripts/safe_alembic_helpers.py
#                           are used (default: ~/releases/current, resolved)
#   HELPER_DIR            — directory holding safe_alembic_helpers.py
#                           (default ${RELEASE_DIR}/infra/scripts)
#   VENV_PYTHON           — python for the helper (default ${RELEASE_DIR}/.venv/bin/python)
#   API_ENV_FILE          — env file with the database URLs (default /etc/juli/api.env)
#   BACKUP_DIR            — destination (default ~/backups)
#   BACKUP_LABEL          — file-name suffix (default manual)
#   MIN_MB                — size floor in MB (default 1)
#   MIN_DATA_ENTRIES      — minimum TABLE DATA entries in the TOC (default 10)
#   DISK_MARGIN_MB        — free-space headroom beyond 1.5x the DB size (default 512)
#   BACKUP_RETENTION_DAYS — delete dumps older than N days (default 14)
#   KEEP_BACKUPS          — if set, keep at most this many dumps (overrides days)
#   BACKUP_MIN_INTERVAL_HOURS — cadence guard (default 0 = always dump). When > 0, exit
#                           0 without dumping if the newest juli-pre-migrate-*.dump in
#                           BACKUP_DIR is younger than this many hours. Any dump counts,
#                           so a migration deploy's dump also resets the clock. The
#                           daily timer sets 72 (every 3 days, D72 egress budget:
#                           each full dump is a full copy of production over the wire).
set -euo pipefail
umask 077

REQUIRED_TABLES=(alembic_version users shops tiktok_credentials)

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { echo "BACKUP FAILED: $*" >&2; exit 1; }

RELEASE_DIR="${RELEASE_DIR:-$(readlink -f "${HOME}/releases/current" 2>/dev/null || true)}"
[ -n "${RELEASE_DIR}" ] && [ -d "${RELEASE_DIR}" ] || fail "no release directory (RELEASE_DIR / ~/releases/current)"
HELPER_DIR="${HELPER_DIR:-${RELEASE_DIR}/infra/scripts}"
VENV_PYTHON="${VENV_PYTHON:-${RELEASE_DIR}/.venv/bin/python}"
API_ENV_FILE="${API_ENV_FILE:-/etc/juli/api.env}"
BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
BACKUP_LABEL="${BACKUP_LABEL:-manual}"
MIN_MB="${MIN_MB:-1}"
MIN_DATA_ENTRIES="${MIN_DATA_ENTRIES:-10}"
DISK_MARGIN_MB="${DISK_MARGIN_MB:-512}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
BACKUP_MIN_INTERVAL_HOURS="${BACKUP_MIN_INTERVAL_HOURS:-0}"

[[ "${BACKUP_LABEL}" =~ ^[A-Za-z0-9._-]+$ ]] || fail "BACKUP_LABEL must be [A-Za-z0-9._-]+ (got '${BACKUP_LABEL}')"
[[ "${BACKUP_MIN_INTERVAL_HOURS}" =~ ^[0-9]+$ ]] || fail "BACKUP_MIN_INTERVAL_HOURS must be a whole number of hours (got '${BACKUP_MIN_INTERVAL_HOURS}')"

# Cadence guard, before any database contact: a skipped run costs no egress.
if [ "${BACKUP_MIN_INTERVAL_HOURS}" -gt 0 ] && [ -d "${BACKUP_DIR}" ]; then
    # shellcheck disable=SC2012  # our own fixed-pattern file names; need mtime order
    NEWEST="$(ls -1t "${BACKUP_DIR}"/juli-pre-migrate-*.dump 2>/dev/null | head -n 1 || true)"
    if [ -n "${NEWEST}" ]; then
        NOW="$(date +%s)"
        MTIME="$(stat -c %Y "${NEWEST}" 2>/dev/null || stat -f %m "${NEWEST}")"
        AGE_H=$(( (NOW - MTIME) / 3600 ))
        if [ "${AGE_H}" -lt "${BACKUP_MIN_INTERVAL_HOURS}" ]; then
            log "newest dump ${NEWEST} is ${AGE_H} h old (< BACKUP_MIN_INTERVAL_HOURS=${BACKUP_MIN_INTERVAL_HOURS}) — dump skipped"
            exit 0
        fi
        log "newest dump ${NEWEST} is ${AGE_H} h old (>= ${BACKUP_MIN_INTERVAL_HOURS} h) — dumping"
    fi
fi
HELPER="${HELPER_DIR}/safe_alembic_helpers.py"
[ -x "${VENV_PYTHON}" ] || fail "release venv python missing: ${VENV_PYTHON}"
[ -f "${HELPER}" ] || fail "helper missing: ${HELPER}"
[ -f "${API_ENV_FILE}" ] || fail "${API_ENV_FILE} missing"
command -v pg_dump >/dev/null || fail "pg_dump not installed"
command -v pg_restore >/dev/null || fail "pg_restore not installed"

set -a
# shellcheck disable=SC1090
. "${API_ENV_FILE}"
set +a
export PYTHONPATH="${HELPER_DIR}:${PYTHONPATH:-}"
helper() { "${VENV_PYTHON}" "${HELPER}" "$@"; }

log "backup-database starting (label=${BACKUP_LABEL}, RELEASE_DIR=${RELEASE_DIR}, BACKUP_DIR=${BACKUP_DIR})"

# Owner role or nothing: under RLS a runtime-role dump is valid and empty.
PRIV="$(helper verify-migration-privileges 2>&1)" || fail "${PRIV}"
log "migration privileges: ${PRIV}"

DB_BYTES="$(helper estimate-db-bytes)" || fail "could not reach the database"
mkdir -p "${BACKUP_DIR}"
NEED=$(( DB_BYTES * 3 / 2 + DISK_MARGIN_MB * 1024 * 1024 ))
HAVE=$(( $(df -Pk "${BACKUP_DIR}" | awk 'NR==2 {print $4}') * 1024 ))
log "database ~$(( DB_BYTES / 1048576 )) MiB; need ~$(( NEED / 1048576 )) MiB free, have ~$(( HAVE / 1048576 )) MiB"
[ "${HAVE}" -ge "${NEED}" ] || fail "insufficient disk space in ${BACKUP_DIR}"

URL="$(helper migration-db-url)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="${BACKUP_DIR}/juli-pre-migrate-${TS}-${BACKUP_LABEL}.dump"
PARTIAL="${FILE}.partial"
trap 'rm -f "${PARTIAL}" "${PARTIAL}.toc"' EXIT
log "pg_dump -Fc -> ${FILE}"
pg_dump -Fc -f "${PARTIAL}" "${URL}" || fail "pg_dump exited non-zero"

# Verify before the file earns its final name.
[ -s "${PARTIAL}" ] || fail "dump is empty"
BYTES="$(wc -c < "${PARTIAL}" | tr -d ' ')"
helper verify-backup-size-floor --bytes "${BYTES}" --min-mb "${MIN_MB}" \
    || fail "dump is ${BYTES} bytes, below the ${MIN_MB} MB floor"
pg_restore --list "${PARTIAL}" > "${PARTIAL}.toc" || fail "pg_restore --list cannot read the dump"
DATA_ENTRIES="$(grep -c ' TABLE DATA ' "${PARTIAL}.toc" || true)"
[ "${DATA_ENTRIES}" -ge "${MIN_DATA_ENTRIES}" ] \
    || fail "dump TOC has only ${DATA_ENTRIES} TABLE DATA entries (floor ${MIN_DATA_ENTRIES})"
for t in "${REQUIRED_TABLES[@]}"; do
    grep -qE " TABLE DATA public ${t} " "${PARTIAL}.toc" || fail "dump TOC has no data for public.${t}"
done
mv -f "${PARTIAL}" "${FILE}"
( cd "${BACKUP_DIR}" && sha256sum "$(basename "${FILE}")" > "$(basename "${FILE}").sha256" )
log "BACKUP OK: ${FILE} (${BYTES} bytes, ~$(( BYTES / 1048576 )) MiB, ${DATA_ENTRIES} TABLE DATA entries)"
# One parseable line per dump, to measure egress: journalctl -u juli-db-backup | grep DUMP_SIZE
log "DUMP_SIZE label=${BACKUP_LABEL} bytes=${BYTES} db_bytes=${DB_BYTES}"
log "sha256: $(cut -d' ' -f1 "${FILE}.sha256")"
log "restore (owner, see safe-alembic-upgrade.sh): pg_restore -e -d \"\${DATABASE_DIRECT_URL}\" --clean --if-exists ${FILE}"

# Rotation: same policy and glob as safe-alembic-upgrade.sh, which now runs only on
# migration deploys — so without this the daily dumps would never be rotated. The
# dump just written is the newest, so it is never a candidate. Its .sha256 goes too.
rotate_one() {
    log "rotating backup ($1): removing $2"
    rm -f "$2" "$2.sha256"
}
if [ -n "${KEEP_BACKUPS:-}" ]; then
    # shellcheck disable=SC2012  # our own fixed-pattern file names; need mtime order
    while IFS= read -r old; do
        [ -n "${old}" ] || continue
        rotate_one "keep ${KEEP_BACKUPS}" "${old}"
    done < <(ls -1t "${BACKUP_DIR}"/juli-pre-migrate-*.dump 2>/dev/null | tail -n "+$(( KEEP_BACKUPS + 1 ))" || true)
else
    while IFS= read -r old; do
        [ -n "${old}" ] || continue
        rotate_one "older than ${BACKUP_RETENTION_DAYS} days" "${old}"
    done < <(find "${BACKUP_DIR}" -maxdepth 1 -name 'juli-pre-migrate-*.dump' -mtime "+${BACKUP_RETENTION_DAYS}" -print 2>/dev/null || true)
fi
log "backup-database complete"
