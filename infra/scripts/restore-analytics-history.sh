#!/usr/bin/env bash
# Restore the analytics history destroyed by the 2026-07-30 production wipe (#789).
#
# VPS-local only (ADR-027): the dump contains OAuth tokens and commerce PII and must
# never leave this host. No Partner API calls are made — this is a pure data restore.
#
# Context: migration tests run against the production database (#734) dropped
# analytics_performance_intervals (6,662 rows) and analytics_backfill_partitions (512)
# between 06:15 and 08:47 UTC on 2026-07-30. The newest dump still holding that data is
# juli-pre-migrate-20260730T061519Z.dump; every later dump has zero rows.
#
# Usage (on the VPS, as root):
#   ./infra/scripts/restore-analytics-history.sh --dry-run   # inspect, write nothing
#   ./infra/scripts/restore-analytics-history.sh             # restore
#
# Env overrides:
#   DUMP_FILE     — dump to restore from (default resolves the 20260730T061519Z dump)
#   BACKUP_DIR    — where dumps live (default ~/backups)
#   API_ENV_FILE  — env file providing DATABASE_URL (default /etc/juli/api.env)
#   SHOP_ID       — shop to scope the restore to (default $DEMO_REFERENCE_SHOP_ID)
#
# Exit codes: 0 success (or dry-run clean), 1 precondition failed or restore error.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-${HOME}/backups}"
API_ENV_FILE="${API_ENV_FILE:-/etc/juli/api.env}"
DEFAULT_DUMP="juli-pre-migrate-20260730T061519Z.dump"
DUMP_FILE="${DUMP_FILE:-${BACKUP_DIR}/${DEFAULT_DUMP}}"
DRY_RUN="false"

# Measured from the dump — used to verify we restored what we expected.
EXPECT_PERF_ROWS=6662
EXPECT_PARTITION_ROWS=512

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "FAIL: $*" >&2; exit 1; }

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN="true" ;;
        *) fail "unknown argument: ${arg} (supported: --dry-run)" ;;
    esac
done

command -v pg_restore >/dev/null 2>&1 || fail "pg_restore not found"
command -v psql >/dev/null 2>&1 || fail "psql not found"

[ -f "${API_ENV_FILE}" ] || fail "${API_ENV_FILE} does not exist"
set -a
# shellcheck disable=SC1090
source "${API_ENV_FILE}"
set +a

[ -n "${DATABASE_URL:-}" ] || fail "DATABASE_URL not set in ${API_ENV_FILE}"
# The app URL may carry the asyncpg driver; psql needs the plain form.
PGURL="${DATABASE_URL//+asyncpg/}"

SHOP_ID="${SHOP_ID:-${DEMO_REFERENCE_SHOP_ID:-}}"
[ -n "${SHOP_ID}" ] || fail "SHOP_ID or DEMO_REFERENCE_SHOP_ID must be set"

[ -f "${DUMP_FILE}" ] || fail "dump not found: ${DUMP_FILE}"
log "dump:    ${DUMP_FILE} ($(wc -c < "${DUMP_FILE}" | tr -d ' ') bytes)"
log "shop_id: ${SHOP_ID}"
log "mode:    $([ "${DRY_RUN}" = "true" ] && echo 'dry-run (no writes)' || echo 'restore')"

# --- 1. The dump must actually contain the data -----------------------------------
count_in_dump() {
    pg_restore --data-only --table="$1" -f - "${DUMP_FILE}" 2>/dev/null \
        | awk '/^COPY /{c=1;next} /^\\\.$/{c=0} c{n++} END{print n+0}'
}
perf_in_dump="$(count_in_dump analytics_performance_intervals)"
part_in_dump="$(count_in_dump analytics_backfill_partitions)"
log "dump contains: analytics_performance_intervals=${perf_in_dump} analytics_backfill_partitions=${part_in_dump}"

[ "${perf_in_dump}" -eq "${EXPECT_PERF_ROWS}" ] \
    || fail "expected ${EXPECT_PERF_ROWS} analytics rows in dump, found ${perf_in_dump} — wrong dump?"
[ "${part_in_dump}" -eq "${EXPECT_PARTITION_ROWS}" ] \
    || fail "expected ${EXPECT_PARTITION_ROWS} partition rows in dump, found ${part_in_dump} — wrong dump?"

# --- 2. Target tables must be empty ------------------------------------------------
# A non-zero count means someone already restored, or new data has accrued. Either way
# this script must not run: it appends, and would duplicate or interleave rows.
perf_live="$(psql "${PGURL}" -At -c "SELECT count(*) FROM analytics_performance_intervals;")"
part_live="$(psql "${PGURL}" -At -c "SELECT count(*) FROM ops.analytics_backfill_partitions;")"
log "production currently: analytics_performance_intervals=${perf_live} ops.analytics_backfill_partitions=${part_live}"

if [ "${perf_live}" -ne 0 ] || [ "${part_live}" -ne 0 ]; then
    fail "target tables are not empty (${perf_live}/${part_live}) — refusing to append. Investigate before restoring."
fi

# --- 3. Schema compatibility -------------------------------------------------------
# The dump predates migrations 021-025. Its COPY carries an explicit column list; the
# load succeeds only if every one of those columns still exists. Columns added since are
# fine (they take defaults); a renamed or dropped column is a hard stop.
pg_restore --data-only --table=analytics_performance_intervals -f - "${DUMP_FILE}" 2>/dev/null \
    | grep '^COPY ' | sed 's/.*(\(.*\)) FROM stdin;/\1/' | tr ',' '\n' | tr -d ' ' | sort > /tmp/_dump_cols.txt
psql "${PGURL}" -At -c "SELECT column_name FROM information_schema.columns
                        WHERE table_name='analytics_performance_intervals'
                          AND table_schema='public' ORDER BY 1;" | sort > /tmp/_prod_cols.txt
missing="$(comm -23 /tmp/_dump_cols.txt /tmp/_prod_cols.txt)"
rm -f /tmp/_dump_cols.txt /tmp/_prod_cols.txt
if [ -n "${missing}" ]; then
    fail "columns present in dump but missing from production: ${missing//$'\n'/, }"
fi
log "schema check: every dumped column exists in production"

if [ "${DRY_RUN}" = "true" ]; then
    log "DRY RUN COMPLETE — all preconditions pass. Re-run without --dry-run to restore."
    exit 0
fi

# --- 4. Restore --------------------------------------------------------------------
log "restoring analytics_performance_intervals"
pg_restore --no-owner --no-acl --data-only \
    --table=analytics_performance_intervals -d "${PGURL}" "${DUMP_FILE}" \
    || fail "pg_restore failed for analytics_performance_intervals"

# analytics_backfill_partitions moved public.* -> ops.* in #604, after this dump was
# taken, so the COPY target has to be rewritten. Restoring these checkpoints matters as
# much as the data: they mark partitions complete, so no later backfill re-fetches this
# window from the Partner API.
log "restoring analytics_backfill_partitions into ops schema"
pg_restore --no-owner --no-acl --data-only \
    --table=analytics_backfill_partitions -f - "${DUMP_FILE}" 2>/dev/null \
    | sed 's/^COPY public\.analytics_backfill_partitions/COPY ops.analytics_backfill_partitions/' \
    | psql "${PGURL}" -v ON_ERROR_STOP=1 \
    || fail "restore failed for ops.analytics_backfill_partitions"

# --- 5. Verify ---------------------------------------------------------------------
perf_after="$(psql "${PGURL}" -At -c "SELECT count(*) FROM analytics_performance_intervals;")"
part_after="$(psql "${PGURL}" -At -c "SELECT count(*) FROM ops.analytics_backfill_partitions;")"
scoped="$(psql "${PGURL}" -At -c "SELECT count(*) FROM analytics_performance_intervals WHERE shop_id='${SHOP_ID}';")"

log "after restore: analytics_performance_intervals=${perf_after} (shop-scoped ${scoped}) ops.analytics_backfill_partitions=${part_after}"
psql "${PGURL}" -c "SELECT grain, count(*), min(start_date), max(start_date)
                    FROM analytics_performance_intervals GROUP BY 1 ORDER BY 1;"

[ "${perf_after}" -eq "${EXPECT_PERF_ROWS}" ] \
    || fail "expected ${EXPECT_PERF_ROWS} analytics rows after restore, got ${perf_after}"
[ "${part_after}" -eq "${EXPECT_PARTITION_ROWS}" ] \
    || fail "expected ${EXPECT_PARTITION_ROWS} partition rows after restore, got ${part_after}"
[ "${scoped}" -eq "${EXPECT_PERF_ROWS}" ] \
    || fail "expected all ${EXPECT_PERF_ROWS} rows on shop ${SHOP_ID}, got ${scoped}"

log "RESTORE PASS"
log "ctor and live_hours stay unavailable until the next hourly reconcile recomputes gold."
log "Verify then with:"
log "  psql \"\$PGURL\" -c \"SELECT k.key, k.value->>'availability', k.value->>'value' FROM gold.kpi_envelopes e, jsonb_each(e.payload->'kpis') k ORDER BY 1;\""
