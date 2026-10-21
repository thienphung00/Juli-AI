#!/usr/bin/env bash
# Roll production back (or forward) to an earlier deploy, all three lanes together,
# without a rebuild and without touching the database (fast-track P57, D66).
#
# WHAT IS LIVE (deploy.sh's header has the full mechanics):
#   lane     slots (loopback)  serving unit (transient)       nginx include (source of truth)
#   api      8000 / 8020       juli-api-candidate-<port>      /etc/nginx/juli/api-upstream.conf
#   demo     3001 / 3021       juli-demo-candidate-<port>     /etc/nginx/juli/demo-upstream.conf
#   landing  3007 / 3027       juli-landing-candidate-<port>  /etc/nginx/juli/landing-upstream.conf
#   worker   -                 juli-celery-worker.service     (runs ~/releases/current)
#   beat     -                 juli-celery-beat.service       (runs ~/releases/current)
# The durable juli-api / juli-demo / juli-landing units exist only so a REBOOT brings
# each lane back on its last live port (/etc/juli/<lane>-runtime.env). They are not
# what serves after a deploy, so `systemctl is-active juli-api` is NOT a health check.
# juli-web (the old dashboard on :3000) is retired and is not touched here.
#
# WHAT "A RELEASE" IS. ~/releases/<short-sha> is one git worktree shared by every lane.
# A deploy builds only the lanes whose paths changed, so a release dir carries
#   .venv/bin/uvicorn                    if the API lane ran in that deploy
#   apps/demo/node_modules/.bin/next     if the Demo lane ran (DEMO_ARTIFACT_TARBALL)
#   apps/landing/node_modules/.bin/next  if the Landing lane ran (LANDING_ARTIFACT_TARBALL)
# ~/releases/deploy-history.log gets "<utc> <sha> <dir>" after every successful deploy.
# The state right after deploy #k is therefore, per lane, the newest entry <= k whose
# dir carries that lane's artifact. That state is what this script restores, for all
# three lanes at once -- never "each lane's own previous release".
#
# DEFAULT TARGET. The deploy before the one that is live now ("live now" = the last
# deploy line, or the deploy a later ROLLBACK-TO line returned to), skipping any
# release a rollback already moved back away from (after A, B, C, a rollback to B and a
# new deploy D, "previous" is B, not the rejected C). Run it again and it goes one
# deploy further back. To go forward again, name the newer SHA: rolling forward is the
# same operation with a newer target.
#
# HOW EACH LANE MOVES (the deploy's own candidate-first pattern, no rebuild):
#   api      the target's venv on the free slot -> /health 2xx + response shape ->
#            nginx include switch + graceful reload -> api-runtime.env + the target's
#            juli-api.service -> ~/releases/current -> public check (undo on failure)
#            -> the target's Celery units installed, worker + beat restarted, the
#            worker's routed queues checked.
#   demo     rollback-demo-release.sh (the #839 lane) -> public check (undo on failure).
#   landing  the target's artifact on the free slot -> 2xx + asset check -> switch +
#            reload -> landing-runtime.env -> ~/releases/landing-current -> public check
#            (undo on failure).
# Nothing public moves until the target answers on loopback. Order: going BACK,
# landing -> demo -> api (older frontends against the newer, additive-only API); going
# FORWARD, api -> demo -> landing (as deploy.sh). The first failing lane stops the run;
# lanes already moved stay moved (each is healthy on its own) and the summary says so.
#
# THE DATABASE IS NEVER TOUCHED: no migration, no downgrade, no restore. Migrations are
# forward-only and gated additive-only (#834), so older code runs on the newer schema.
# If the rolled-back release shipped a migration and the older code does NOT work with
# it, restoring the verified pre-deploy dump (~/backups/juli-pre-migrate-*.dump, from
# fasttrack-deploy.yml's backup job) is a separate owner decision that loses every
# write since the dump -- see docs/runbooks/rollback-runbook.md. --plan names any
# migration the target's code does not know about.
#
# Usage (on the VPS as root, from the canonical clone ~/Juli-AI-v2, or via rollback.yml):
#   ./infra/scripts/rollback-release.sh --plan [TARGET]   resolve and print; change nothing
#   ./infra/scripts/rollback-release.sh [TARGET]          roll back (or forward) to TARGET
#   ./infra/scripts/rollback-release.sh --verify          health summary only; change nothing
#   --lanes "api demo landing"   default all three; a subset is for emergencies only
#   TARGET: a full or short (>= 7 hex) SHA from deploy-history.log, or a release dir
#           name under ~/releases. Empty = the previous deploy (see above).
#
# Env (production defaults; tests/unit/test_rollback_release_simulation.py overrides
# them): RELEASES_ROOT, NGINX_UPSTREAM_DIR, ETC_JULI_DIR, SYSTEMD_UNIT_DIR, API_ENV_FILE,
# FRONTEND_ENV_FILE, DEMO_RUNTIME_ENV, RECORDS_DIR, CANDIDATE_TIMEOUT_SECS (120),
# PUBLIC_CHECK_TIMEOUT_SECS (45), HEALTH_TIMEOUT_SECS (60), ROLLBACK_PUBLIC_CHECKS=1
# (0 skips the public https checks), ROLLBACK_REQUIRE_CELERY=1, ROLLBACK_CELERY_PING=0
# (1 adds `celery inspect ping` to the summary).
#
# Exit: 0 PASS (or nothing to do), 1 FAIL (the summary says what moved), 2 usage error.
set -euo pipefail

# rollback.yml refuses a VPS clone whose script lacks this marker: an older clone runs
# the pre-P57 script, which restarted the retired juli-web and waited for :3000.
# shellcheck disable=SC2034
ROLLBACK_INTERFACE=2

_RB_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The lane table, slot mechanics, nginx switch and Celery queue check live in deploy.sh
# exactly once; DEPLOY_SOURCE_ONLY=1 defines them and deploys nothing.
DEPLOY_SOURCE_ONLY=1
# shellcheck source=infra/scripts/deploy.sh
source "${_RB_SCRIPT_DIR}/deploy.sh"

HISTORY_LOG="${RELEASES_ROOT}/deploy-history.log"
ETC_JULI_DIR="${ETC_JULI_DIR:-/etc/juli}"
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
FRONTEND_ENV_FILE="${FRONTEND_ENV_FILE:-${ETC_JULI_DIR}/frontend.env}"
DEMO_RUNTIME_ENV="${DEMO_RUNTIME_ENV:-${ETC_JULI_DIR}/demo-runtime.env}"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
ROLLBACK_PUBLIC_CHECKS="${ROLLBACK_PUBLIC_CHECKS:-1}"
ROLLBACK_REQUIRE_CELERY="${ROLLBACK_REQUIRE_CELERY:-1}"
ROLLBACK_CELERY_PING="${ROLLBACK_CELERY_PING:-0}"
DEMO_ROLLBACK_SCRIPT="${DEMO_ROLLBACK_SCRIPT:-${CANONICAL_ROOT}/infra/scripts/rollback-demo-release.sh}"
MIGRATIONS_REL="backend/src/juli_backend/database/migrations/versions"
ALL_LANES="api demo landing"
CELERY_UNITS="juli-celery-worker juli-celery-beat"

usage() {
    awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "${BASH_SOURCE[0]}"
}

# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------

# Physical path of a dir, or of the dir a symlink names. Empty if it does not exist.
realdir() { (cd "$1" 2>/dev/null && pwd -P) || true; }

lane_artifact() {
    case "$1" in
        api) echo ".venv/bin/uvicorn" ;;
        demo) echo "apps/demo/node_modules/.bin/next" ;;
        landing) echo "apps/landing/node_modules/.bin/next" ;;
        *) return 1 ;;
    esac
}

lane_has_artifact() { [ -x "$2/$(lane_artifact "$1")" ]; }

lane_live_dir() { realdir "$(lane_current "$1")"; }

# Atomic symlink repoint. GNU `mv -T` renames over the link itself; where mv has no -T
# (BSD, the local simulation) os.replace is the same rename(2). Never a plain `mv -f`,
# which would move the new link INTO the directory the old one names.
repoint_symlink() {
    local target="$1" link="$2"
    ln -sfn "${target}" "${link}.tmp" || return 1
    mv -Tf "${link}.tmp" "${link}" 2>/dev/null ||
        python3 -c 'import os, sys; os.replace(sys.argv[1], sys.argv[2])' "${link}.tmp" "${link}"
}

is_2xx() { [ "${#1}" -eq 3 ] && [ "${1#2}" != "$1" ]; }

stop_unit() {
    systemctl stop "$1" >/dev/null 2>&1 || true
    systemctl reset-failed "$1" >/dev/null 2>&1 || true
}

# --------------------------------------------------------------------------------------
# History. Deploy entries are "<utc> <40-hex sha> <dir>" (deploy.sh). This script adds
# "<utc> ROLLBACK-TO <dir> <sha> lanes=..." after a full rollback, ROLLBACK-PARTIAL
# after a --lanes subset (field 3 is the dir either way, which is what
# lib/prune-releases.sh keeps).
# --------------------------------------------------------------------------------------

E_SHA=()
E_DIR=()
N_ENTRIES=0

load_history() {
    local _ts f2 f3 _rest
    N_ENTRIES=0
    while read -r _ts f2 f3 _rest; do
        if [[ "${f2}" =~ ^[0-9a-f]{40}$ ]] && [ -n "${f3}" ]; then
            E_SHA[N_ENTRIES]="${f2}"
            E_DIR[N_ENTRIES]="${f3}"
            N_ENTRIES=$((N_ENTRIES + 1))
        fi
    done <"${HISTORY_LOG}"
}

# Replays the history to find the deploy whose state is live now (ANCHOR) and the
# releases a rollback moved BACK away from (ROLLED_AWAY, "|dir|" entries): those are
# known-bad, so the default target skips them. After A, B, C, a rollback to B and a new
# deploy D, "previous" is B, not the rejected C. Moving forward again to a release, or
# redeploying it, clears its mark (the drill's back-and-forward leaves nothing marked).
ANCHOR=-1
ROLLED_AWAY="|"

replay_history() {
    local _ts f2 f3 f4 _rest k=0 i idx
    ANCHOR=-1 ROLLED_AWAY="|"
    while read -r _ts f2 f3 f4 _rest; do
        if [[ "${f2}" =~ ^[0-9a-f]{40}$ ]] && [ -n "${f3}" ]; then
            ANCHOR="${k}"
            ROLLED_AWAY="${ROLLED_AWAY//|${f3}|/|}"
            k=$((k + 1))
        elif [ "${f2}" = "ROLLBACK-TO" ] && [ -n "${f3}" ]; then
            idx=-1
            for ((i = k - 1; i >= 0; i--)); do
                if [ "${E_DIR[i]}" = "${f3}" ] && { [ -z "${f4:-}" ] || [ "${E_SHA[i]}" = "${f4}" ]; }; then
                    idx="${i}"
                    break
                fi
            done
            if [ "${idx}" -lt 0 ]; then
                echo "FAIL: a ROLLBACK-TO line names ${f3}, which no earlier deploy entry carries." >&2
                return 1
            fi
            if [ "${ANCHOR}" -ge 0 ] && [ "${idx}" -lt "${ANCHOR}" ]; then
                ROLLED_AWAY="${ROLLED_AWAY}${E_DIR[ANCHOR]}|"
            else
                ROLLED_AWAY="${ROLLED_AWAY//|${f3}|/|}"
            fi
            ANCHOR="${idx}"
        fi
    done <"${HISTORY_LOG}"
}

rolled_away() { case "${ROLLED_AWAY}" in *"|$1|"*) return 0 ;; esac; return 1; }

resolve_target_index() {
    local target="$1" anchor="$2" i
    if [ -z "${target}" ]; then
        i=$((anchor - 1))
        # A redeploy of the same SHA is the same release, not "the previous one"; a
        # release a rollback already moved away from is not a target either.
        while [ "${i}" -ge 0 ] && { [ "${E_DIR[i]}" = "${E_DIR[anchor]}" ] || rolled_away "${E_DIR[i]}"; }; do
            i=$((i - 1))
        done
        if [ "${i}" -lt 0 ]; then
            echo "FAIL: there is no usable deploy before #${anchor} in ${HISTORY_LOG}." >&2
            return 1
        fi
        echo "${i}"
        return 0
    fi
    for ((i = N_ENTRIES - 1; i >= 0; i--)); do
        case "${E_SHA[i]}" in "${target}"*)
            echo "${i}"
            return 0
            ;;
        esac
        if [ "$(basename "${E_DIR[i]}")" = "${target}" ]; then
            echo "${i}"
            return 0
        fi
    done
    echo "FAIL: '${target}' matches no deploy in ${HISTORY_LOG}." >&2
    return 1
}

# The dir a lane ran right after deploy #k: the newest entry <= k carrying the lane's
# artifact. A missing (pruned) dir on the way down makes that unknowable -- that deploy
# may or may not have shipped the lane -- so it fails instead of guessing.
lane_dir_at() {
    local lane="$1" k="$2" i d
    for ((i = k; i >= 0; i--)); do
        d="${E_DIR[i]}"
        if [ ! -d "${d}" ]; then
            echo "FAIL: ${lane}: release ${d} (deploy #${i}) no longer exists (pruned), so" >&2
            echo "      what ${lane} ran after deploy #${k} cannot be reconstructed." >&2
            return 1
        fi
        if lane_has_artifact "${lane}" "${d}"; then
            realdir "${d}"
            return 0
        fi
    done
    echo "FAIL: ${lane}: no release at or before deploy #${k} carries $(lane_artifact "${lane}")." >&2
    return 1
}

# Migration files the live API code has and the target's code does not.
migrations_ahead() {
    local live="$1" target="$2" f name
    [ -d "${live}/${MIGRATIONS_REL}" ] || return 0
    for f in "${live}/${MIGRATIONS_REL}"/*.py; do
        [ -e "${f}" ] || continue
        name="$(basename "${f}")"
        [ "${name}" = "__init__.py" ] && continue
        [ -e "${target}/${MIGRATIONS_REL}/${name}" ] || echo "${name}"
    done
}

# --------------------------------------------------------------------------------------
# Unit + runtime-env install: deploy.sh's write_runtime_env / sync_celery_unit, but from
# the TARGET release, and with overridable /etc paths so the simulation can run them.
# --------------------------------------------------------------------------------------

install_release_unit() {
    local release_dir="$1" unit="$2" src dest
    src="${release_dir}/infra/systemd/${unit}.service"
    dest="${SYSTEMD_UNIT_DIR}/${unit}.service"
    [ -f "${src}" ] || { echo "FAIL: ${src} not found in the target release" >&2; return 1; }
    if ! install -m 0644 "${src}" "${dest}"; then
        echo "FAIL: could not install ${dest} from ${release_dir}" >&2
        return 1
    fi
    systemctl daemon-reload || return 1
    if ! cmp -s "${src}" "${dest}"; then
        echo "FAIL: ${dest} still differs from ${src} after install" >&2
        return 1
    fi
}

# Reboot durability: the durable unit must come back on the port nginx now names.
install_runtime_env() {
    local lane="$1" port="$2" release_dir="$3" var file tmp
    case "${lane}" in
        api) var=API_LIVE_PORT file="${ETC_JULI_DIR}/api-runtime.env" ;;
        landing) var=LANDING_LIVE_PORT file="${ETC_JULI_DIR}/landing-runtime.env" ;;
        *) return 1 ;;
    esac
    mkdir -p "$(dirname "${file}")" || return 1
    tmp="${file}.tmp.$$"
    printf '# Written by rollback-release.sh (P57). Do not edit.\n%s=%s\n' "${var}" "${port}" >"${tmp}" || return 1
    mv -f "${tmp}" "${file}" || return 1
    install_release_unit "${release_dir}" "juli-${lane}" || return 1
    if [ "${lane}" = "api" ]; then
        # As deploy.sh (#1069): the durable unit must not hold a slot port.
        systemctl stop juli-api >/dev/null 2>&1 || true
        systemctl reset-failed juli-api >/dev/null 2>&1 || true
    fi
}

# --------------------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------------------

# deploy.sh's verify_api_shape, through curl: /health is JSON with status=="ok".
# (/v1/demo/analytics was retired by fast track P61-D / D72.5 -- 410 Gone.)
verify_api_shape_curl() {
    local base="$1" health
    health="$(curl -s -m 15 -H 'User-Agent: juli-rollback-verify/1.0' "${base}/health" 2>/dev/null || true)"
    python3 - "${health}" <<'PY'
import json, sys
try:
    health = json.loads(sys.argv[1])
except ValueError as exc:
    sys.exit(f"FAIL: API response is not JSON ({exc})")
if not isinstance(health, dict) or health.get("status") != "ok":
    sys.exit(f"FAIL: /health shape wrong: {sys.argv[1][:200]!r}")
print("PASS: API /health carries the expected response shape")
PY
}

# Poll until 2xx or HEALTH_TIMEOUT_SECS; echoes the last code.
poll_2xx() {
    local url="$1" deadline=$((SECONDS + HEALTH_TIMEOUT_SECS)) code="000"
    while :; do
        code="$(http_code "${url}")"
        if is_2xx "${code}"; then
            echo "${code}"
            return 0
        fi
        [ "${SECONDS}" -ge "${deadline}" ] && break
        sleep 3
    done
    echo "${code}"
    return 1
}

api_health_ok() {
    local url="$1" body="" deadline=$((SECONDS + HEALTH_TIMEOUT_SECS))
    while :; do
        body="$(curl -s -m 10 "${url}" 2>/dev/null || true)"
        if python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1]).get("status") == "ok" else 1)' \
            "${body}" 2>/dev/null; then
            return 0
        fi
        [ "${SECONDS}" -ge "${deadline}" ] && break
        sleep 3
    done
    echo "${body:0:120}"
    return 1
}

unit_active() {
    local unit="$1" deadline=$((SECONDS + HEALTH_TIMEOUT_SECS))
    while :; do
        systemctl is-active --quiet "${unit}" && return 0
        [ "${SECONDS}" -ge "${deadline}" ] && return 1
        sleep 2
    done
}

# Optional: the worker answers on the broker. Reads api.env in a subshell (for the
# broker URL) and prints none of it.
celery_ping() {
    local release_dir="$1" runner=()
    command -v timeout >/dev/null 2>&1 && runner=(timeout 45)
    (
        set -a
        # shellcheck disable=SC1090
        . "${API_ENV_FILE}"
        set +a
        ${runner[@]+"${runner[@]}"} "${release_dir}/.venv/bin/celery" \
            -A juli_backend.workers.celery_app inspect ping --timeout 10
    ) 2>&1 | grep -q 'pong'
}

SUMMARY_ROWS=""
SUMMARY_FAILS=0
SUMMARY_TOTAL=0

summary_row() {
    local check="$1" result="$2" detail="${3:-}"
    SUMMARY_ROWS="${SUMMARY_ROWS}$(printf '  %-46s %-5s %s' "${check}" "${result}" "${detail}")"$'\n'
    [ "${result}" = "INFO" ] && return 0
    SUMMARY_TOTAL=$((SUMMARY_TOTAL + 1))
    [ "${result}" = "FAIL" ] && SUMMARY_FAILS=$((SUMMARY_FAILS + 1))
    return 0
}

# The health of what is live NOW (also the whole of --verify).
verify_live() {
    local port code detail unit lane rel path url
    SUMMARY_ROWS="" SUMMARY_FAILS=0 SUMMARY_TOTAL=0

    if port="$(live_port_of api 2>/dev/null)" && [ -n "${port}" ]; then
        if detail="$(api_health_ok "http://127.0.0.1:${port}/health")"; then
            summary_row "api      127.0.0.1:${port}/health" PASS "status=ok"
        else
            summary_row "api      127.0.0.1:${port}/health" FAIL "${detail:-no answer}"
        fi
    else
        summary_row "api      upstream" FAIL "cannot read $(lane_upstream api)"
    fi
    for lane in demo landing; do
        path=/
        [ "${lane}" = "demo" ] && path=/decisions
        if port="$(live_port_of "${lane}" 2>/dev/null)" && [ -n "${port}" ]; then
            if code="$(poll_2xx "http://127.0.0.1:${port}${path}")"; then
                summary_row "$(printf '%-8s' "${lane}") 127.0.0.1:${port}${path}" PASS "HTTP ${code}"
            else
                summary_row "$(printf '%-8s' "${lane}") 127.0.0.1:${port}${path}" FAIL "HTTP ${code}"
            fi
        else
            summary_row "$(printf '%-8s' "${lane}") upstream" FAIL "cannot read $(lane_upstream "${lane}")"
        fi
    done
    for unit in ${CELERY_UNITS}; do
        if ! systemctl cat "${unit}" >/dev/null 2>&1; then
            if [ "${ROLLBACK_REQUIRE_CELERY}" = "1" ]; then
                summary_row "${unit}" FAIL "not installed"
            else
                summary_row "${unit}" SKIP "not installed"
            fi
        elif unit_active "${unit}"; then
            summary_row "${unit}" PASS "active"
        else
            summary_row "${unit}" FAIL "$(systemctl is-active "${unit}" 2>/dev/null || true)"
        fi
    done
    if [ "${ROLLBACK_CELERY_PING}" = "1" ]; then
        rel="$(lane_live_dir api)"
        if [ -n "${rel}" ] && celery_ping "${rel}"; then
            summary_row "celery inspect ping" PASS "pong"
        else
            summary_row "celery inspect ping" FAIL "no pong"
        fi
    fi
    if [ "${ROLLBACK_PUBLIC_CHECKS}" = "1" ]; then
        for lane in ${ALL_LANES}; do
            url="$(lane_public_url "${lane}")"
            if code="$(poll_2xx "${url}")"; then
                summary_row "public   ${url}" PASS "HTTP ${code}"
            else
                summary_row "public   ${url}" FAIL "HTTP ${code}"
            fi
        done
    fi
    for lane in ${ALL_LANES}; do
        summary_row "$(printf '%-8s' "${lane}") ~/releases/$(basename "$(lane_current "${lane}")")" INFO \
            "-> $(lane_live_dir "${lane}")"
    done
}

# print_summary <title> [reason the run failed even if every live check passes]
print_summary() {
    printf '\n== %s ==\n' "$1"
    printf '%s' "${SUMMARY_ROWS}"
    if [ -n "${2:-}" ]; then
        printf 'RESULT: FAIL (%s; live health: %s of %s checks failed)\n' "$2" "${SUMMARY_FAILS}" "${SUMMARY_TOTAL}"
    elif [ "${SUMMARY_FAILS}" -eq 0 ]; then
        printf 'RESULT: PASS (%s checks)\n' "${SUMMARY_TOTAL}"
    else
        printf 'RESULT: FAIL (%s of %s checks failed)\n' "${SUMMARY_FAILS}" "${SUMMARY_TOTAL}"
    fi
}

# --------------------------------------------------------------------------------------
# Lanes. Each function is called as an `if` condition (errexit is off inside), so every
# step that matters is checked explicitly.
# --------------------------------------------------------------------------------------

# These flags MUST match infra/systemd/juli-api.service's ExecStart and deploy.sh's
# candidate (tests/unit/test_deploy_uvicorn_flag_parity.py checks both).
start_api_candidate() {
    local release_dir="$1" port="$2"
    systemd-run --unit="juli-api-candidate-${port}" --collect \
        --property=Type=simple \
        --property=WorkingDirectory="${release_dir}" \
        --property=EnvironmentFile="${API_ENV_FILE}" \
        --property=Restart=no \
        "${release_dir}/.venv/bin/uvicorn" juli_backend.api.main:app \
        --host 127.0.0.1 --port "${port}" --workers 1 \
        --proxy-headers --forwarded-allow-ips=127.0.0.1 >&2
}

# As deploy.sh's landing candidate (same environment as the durable unit).
start_landing_candidate() {
    local release_dir="$1" port="$2"
    systemd-run --unit="juli-landing-candidate-${port}" --collect \
        --property=Type=simple \
        --property=WorkingDirectory="${release_dir}/apps/landing" \
        --property=EnvironmentFile=-"${FRONTEND_ENV_FILE}" \
        --property=Restart=no \
        "${release_dir}/apps/landing/node_modules/.bin/next" start \
        --port "${port}" --hostname 127.0.0.1 >&2
}

# The target must be the only thing that can answer on the free slot, or the loopback
# checks below would pass against whatever already holds it. Normally the drained
# previous candidate (stopped just before this); after a reboot it can be the durable
# unit. Nothing listening = curl's 000.
ensure_port_free() {
    local lane="$1" port="$2"
    [ "$(http_code "http://127.0.0.1:${port}/")" = "000" ] && return 0
    note "${lane}: something still answers on :${port} -- stopping juli-${lane} (it is not serving traffic)"
    systemctl stop "juli-${lane}" >/dev/null 2>&1 || true
    [ "$(http_code "http://127.0.0.1:${port}/")" = "000" ] && return 0
    echo "FAIL: ${lane}: :${port} is still taken by an unknown process; refusing to verify a target there." >&2
    return 1
}

# After a failed public check: traffic back on the previous slot if that instance still
# answers; otherwise it stays on the (loopback-verified) target, and the run fails.
undo_slot_lane() {
    local lane="$1" prev_port="$2" prev_dir="$3" probe="$4" code
    code="$(http_code "http://127.0.0.1:${prev_port}${probe}")"
    if ! is_2xx "${code}"; then
        echo "FAIL: ${lane}: the previous instance on :${prev_port} no longer answers (HTTP ${code});" >&2
        echo "      traffic stays on the target, which passed its loopback checks." >&2
        return 1
    fi
    note "${lane}: automatic undo -- returning traffic to :${prev_port}"
    switch_upstream "${lane}" "${prev_port}" || return 1
    install_runtime_env "${lane}" "${prev_port}" "${prev_dir}" || true
    repoint_symlink "${prev_dir}" "$(lane_current "${lane}")" || return 1
    record_step "${lane}" undo "restored_to_${prev_port}"
}

public_step() {
    local lane="$1" url
    url="$(lane_public_url "${lane}")"
    if [ "${ROLLBACK_PUBLIC_CHECKS}" != "1" ]; then
        record_step "${lane}" public_check "skipped"
        return 0
    fi
    if public_check "${url}"; then
        record_step "${lane}" public_check "passed"
        return 0
    fi
    record_step "${lane}" public_check "failed"
    return 1
}

rollback_lane_api() {
    local target_dir="$1" prev_dir live_port peer unit code
    prev_dir="$(lane_live_dir api)"
    live_port="$(live_port_of api)" || return 1
    peer="$(peer_port_of api "${live_port}")" || return 1
    unit="juli-api-candidate-${peer}"
    log "api: ${prev_dir} -> ${target_dir} (live :${live_port}, target on :${peer})"

    # The free slot holds the drained previous instance (or nothing), never the live one.
    stop_unit "${unit}"
    ensure_port_free api "${peer}" || { record_step api candidate "failed" "port ${peer} taken"; return 1; }
    if ! start_api_candidate "${target_dir}" "${peer}"; then
        record_step api candidate "failed" "systemd-run refused"
        return 1
    fi
    if ! code="$(wait_2xx "http://127.0.0.1:${peer}/health")"; then
        echo "FAIL: api: ${target_dir} never became ready on :${peer} (HTTP ${code}); nothing switched." >&2
        record_step api candidate "failed" "never ready (HTTP ${code})"
        stop_unit "${unit}"
        return 1
    fi
    record_step api candidate "ready" "HTTP ${code}"
    if ! verify_api_shape_curl "http://127.0.0.1:${peer}"; then
        echo "FAIL: api: response shape check failed on :${peer}; nothing switched." >&2
        record_step api verify_shape "failed"
        stop_unit "${unit}"
        return 1
    fi
    record_step api verify_shape "passed"

    if ! switch_upstream api "${peer}"; then
        record_step api cutover "refused"
        stop_unit "${unit}"
        return 1
    fi
    record_step api cutover "switched_to_${peer}"
    if ! install_runtime_env api "${peer}" "${target_dir}"; then
        record_step api runtime_env "failed"
        return 1
    fi
    repoint_symlink "${target_dir}" "$(lane_current api)" || return 1

    if ! public_step api; then
        undo_slot_lane api "${live_port}" "${prev_dir}" /health || true
        return 1
    fi

    # Worker and beat run ~/releases/current, so they follow the API -- with the TARGET
    # release's unit files (its -Q list matches its own task routing).
    for unit in ${CELERY_UNITS}; do
        if ! systemctl cat "${unit}" >/dev/null 2>&1; then
            if [ "${ROLLBACK_REQUIRE_CELERY}" = "1" ]; then
                echo "FAIL: ${unit} is not installed on this host" >&2
                record_step api celery "failed" "${unit} not installed"
                return 1
            fi
            echo "SKIP: ${unit} not installed on this host"
            continue
        fi
        if ! install_release_unit "${target_dir}" "${unit}"; then
            record_step api celery "failed" "${unit} unit install"
            return 1
        fi
        CELERY_VERIFY_SINCE="$(date '+%Y-%m-%d %H:%M:%S')"
        if ! systemctl restart "${unit}"; then
            echo "FAIL: systemctl restart ${unit} failed" >&2
            record_step api celery "failed" "${unit} restart refused"
            return 1
        fi
        if [ "${unit}" = "juli-celery-worker" ] &&
            ! verify_celery_worker_queues "${unit}" "${SYSTEMD_UNIT_DIR}/${unit}.service"; then
            record_step api celery "failed" "${unit} missing routed queue(s)"
            return 1
        fi
    done
    record_step api celery "verified"
}

rollback_lane_landing() {
    local target_dir="$1" prev_dir live_port peer unit code
    prev_dir="$(lane_live_dir landing)"
    live_port="$(live_port_of landing)" || return 1
    peer="$(peer_port_of landing "${live_port}")" || return 1
    unit="juli-landing-candidate-${peer}"
    log "landing: ${prev_dir} -> ${target_dir} (live :${live_port}, target on :${peer})"

    stop_unit "${unit}"
    ensure_port_free landing "${peer}" || { record_step landing candidate "failed" "port ${peer} taken"; return 1; }
    if ! start_landing_candidate "${target_dir}" "${peer}"; then
        record_step landing candidate "failed" "systemd-run refused"
        return 1
    fi
    if ! code="$(wait_2xx "http://127.0.0.1:${peer}/")"; then
        echo "FAIL: landing: ${target_dir} never became ready on :${peer} (HTTP ${code}); nothing switched." >&2
        record_step landing candidate "failed" "never ready (HTTP ${code})"
        stop_unit "${unit}"
        return 1
    fi
    record_step landing candidate "ready" "HTTP ${code}"
    if ! "${VERIFY_HARNESS}" --base-url "http://127.0.0.1:${peer}" --route /; then
        echo "FAIL: landing: asset check failed on :${peer}; nothing switched." >&2
        record_step landing verify_assets "failed"
        stop_unit "${unit}"
        return 1
    fi
    record_step landing verify_assets "passed"

    if ! switch_upstream landing "${peer}"; then
        record_step landing cutover "refused"
        stop_unit "${unit}"
        return 1
    fi
    record_step landing cutover "switched_to_${peer}"
    if ! install_runtime_env landing "${peer}" "${target_dir}"; then
        record_step landing runtime_env "failed"
        return 1
    fi
    repoint_symlink "${target_dir}" "$(lane_current landing)" || return 1

    if ! public_step landing; then
        undo_slot_lane landing "${live_port}" "${prev_dir}" / || true
        return 1
    fi
}

run_demo_rollback() {
    RELEASES_ROOT="${RELEASES_ROOT}" NGINX_UPSTREAM_DIR="${NGINX_UPSTREAM_DIR}" \
        DEMO_RUNTIME_ENV="${DEMO_RUNTIME_ENV}" CANDIDATE_TIMEOUT_SECS="${CANDIDATE_TIMEOUT_SECS}" \
        HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS}" \
        "${DEMO_ROLLBACK_SCRIPT}" "$(basename "$1")"
}

rollback_lane_demo() {
    local target_dir="$1" prev_dir now
    prev_dir="$(lane_live_dir demo)"
    log "demo: ${prev_dir} -> ${target_dir} (via rollback-demo-release.sh)"
    if ! run_demo_rollback "${target_dir}"; then
        record_step demo rollback "failed"
        return 1
    fi
    now="$(lane_live_dir demo)"
    if [ "${now}" != "${target_dir}" ]; then
        echo "FAIL: demo: demo-current names ${now}, expected ${target_dir}." >&2
        record_step demo rollback "failed" "demo-current is ${now}"
        return 1
    fi
    record_step demo rollback "switched"
    if ! public_step demo; then
        note "demo: automatic undo -- back to ${prev_dir}"
        run_demo_rollback "${prev_dir}" || echo "FAIL: demo: the undo failed too" >&2
        return 1
    fi
}

# --------------------------------------------------------------------------------------

rollback_main() {
    local mode=rollback lanes="${ALL_LANES}" target="" lane i
    while [ $# -gt 0 ]; do
        case "$1" in
            --plan) mode=plan ;;
            --verify) mode=verify ;;
            --lanes)
                [ $# -ge 2 ] || { echo "--lanes needs a value" >&2; exit 2; }
                lanes="$2"
                shift
                ;;
            --lanes=*) lanes="${1#--lanes=}" ;;
            -h | --help) usage; exit 0 ;;
            -*) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
            *)
                [ -z "${target}" ] || { echo "only one TARGET may be given" >&2; exit 2; }
                target="$1"
                ;;
        esac
        shift
    done
    lanes="$(printf '%s\n' "${lanes}" | tr ',' ' ' | tr -s ' ' '\n' | awk 'NF' | sort -u | tr '\n' ' ')"
    lanes="${lanes% }"
    [ -n "${lanes}" ] || { echo "--lanes is empty" >&2; exit 2; }
    for lane in ${lanes}; do
        case " ${ALL_LANES} " in
            *" ${lane} "*) ;;
            *) echo "unknown lane '${lane}' (api demo landing)" >&2; exit 2 ;;
        esac
    done
    # The target ends up in paths and a log line; nothing but hex is accepted.
    if [ -n "${target}" ] && ! [[ "${target}" =~ ^[0-9a-f]{7,40}$ ]]; then
        echo "FAIL: TARGET must be a 7-40 character lowercase hex SHA or release dir name (got '${target}')." >&2
        exit 2
    fi

    if [ "${mode}" = "verify" ]; then
        verify_live
        print_summary "live health (--verify; nothing changed)"
        [ "${SUMMARY_FAILS}" -eq 0 ] || exit 1
        return 0
    fi

    [ -f "${HISTORY_LOG}" ] || { echo "FAIL: no ${HISTORY_LOG} found -- nothing to roll back to." >&2; exit 1; }
    load_history
    [ "${N_ENTRIES}" -gt 0 ] || { echo "FAIL: ${HISTORY_LOG} has no deploy entries." >&2; exit 1; }
    local anchor t
    replay_history || exit 1
    anchor="${ANCHOR}"
    if ! t="$(resolve_target_index "${target}" "${anchor}")"; then
        echo "Deploys in ${HISTORY_LOG} (oldest first):" >&2
        for ((i = 0; i < N_ENTRIES; i++)); do echo "  #${i} ${E_SHA[i]:0:12} ${E_DIR[i]}" >&2; done
        exit 1
    fi

    local direction order
    if [ "${t}" -lt "${anchor}" ]; then
        direction="back" order="landing demo api"
    else
        direction="forward" order="api demo landing"
    fi

    # Resolve every lane before anything moves; any doubt stops the run here.
    local plan_fail=0 todo="" live tgt ahead
    log "rollback plan (P57)"
    note "live now : deploy #${anchor} ${E_SHA[anchor]:0:12} ${E_DIR[anchor]}"
    note "target   : deploy #${t} ${E_SHA[t]:0:12} ${E_DIR[t]}  (${direction}: ${order// / -> })"
    for lane in ${order}; do
        case " ${lanes} " in
            *" ${lane} "*) ;;
            *)
                note "$(printf '%-8s' "${lane}"): not requested (--lanes)"
                continue
                ;;
        esac
        live="$(lane_live_dir "${lane}")"
        if ! tgt="$(lane_dir_at "${lane}" "${t}")"; then
            plan_fail=1
            continue
        fi
        if [ "${live}" = "${tgt}" ]; then
            note "$(printf '%-8s' "${lane}"): unchanged (${tgt})"
            continue
        fi
        if [ "${lane}" != "demo" ] && ! live_port_of "${lane}" >/dev/null; then
            plan_fail=1
            continue
        fi
        note "$(printf '%-8s' "${lane}"): ${live:-<none>} -> ${tgt}"
        todo="${todo} ${lane}=${tgt}"
        if [ "${lane}" = "api" ]; then
            ahead="$(migrations_ahead "${live}" "${tgt}" | tr '\n' ' ')"
            if [ -n "${ahead// /}" ]; then
                note "WARN: the database schema stays ahead of the target's code by: ${ahead}"
                note "      (additive-only, so the old code should run; the runbook covers it if not)"
            fi
        fi
    done
    note "database : NOT touched (no migration, no downgrade, no restore)"
    if [ "${plan_fail}" -ne 0 ]; then
        echo "FAIL: the plan could not be resolved; nothing was changed." >&2
        exit 1
    fi
    if [ "${mode}" = "plan" ]; then
        note "--plan: nothing was changed"
        return 0
    fi
    if [ -z "${todo// /}" ]; then
        note "every requested lane is already on the target -- nothing to do"
        verify_live
        print_summary "live health"
        [ "${SUMMARY_FAILS}" -eq 0 ] || exit 1
        return 0
    fi

    local short="${E_SHA[t]:0:7}" item moved="" failed=""
    mkdir -p "${RECORDS_DIR}"
    RECORD_FILE="${RECORDS_DIR}/rollback-$(date -u +%Y%m%dT%H%M%SZ)-${short}.json"
    printf '{"rollback_to": "%s", "direction": "%s", "started_at": "%s", "steps": [\n' \
        "${E_SHA[t]}" "${direction}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"${RECORD_FILE}"

    for item in ${todo}; do
        lane="${item%%=*}"
        tgt="${item#*=}"
        if "rollback_lane_${lane}" "${tgt}"; then
            moved="${moved} ${lane}"
        else
            failed="${lane}"
            break
        fi
    done

    verify_live
    if [ -n "${failed}" ]; then
        record_close "failed:${failed}"
        print_summary "rollback FAILED in lane ${failed}" "the rollback stopped in lane ${failed}"
        echo "Moved to the target:${moved:- nothing}. Stopped at: ${failed}. Each lane is either" >&2
        echo "fully on the target or fully where it was. Fix and re-run, or return with:" >&2
        echo "  $0 ${E_SHA[anchor]:0:12}" >&2
        exit 1
    fi
    local kind=ROLLBACK-TO
    [ "${lanes}" = "api demo landing" ] || kind=ROLLBACK-PARTIAL
    printf '%s %s %s %s lanes=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${kind}" "${E_DIR[t]}" "${E_SHA[t]}" \
        "$(printf '%s' "${moved# }" | tr ' ' ',')" >>"${HISTORY_LOG}"
    if [ "${SUMMARY_FAILS}" -ne 0 ]; then
        record_close "moved_but_unhealthy"
        print_summary "rollback moved:${moved}, but the health summary FAILED"
        exit 1
    fi
    record_close "completed"
    print_summary "rollback to ${short} complete (moved:${moved})"
}

rollback_main "$@"
