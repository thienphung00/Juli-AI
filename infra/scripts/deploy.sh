#!/usr/bin/env bash
# The single deploy command (#843, #844). Deploys every production deployable —
# API, Demo, Landing — rebuilding and restarting only what actually changed.
#
# Change detection: each lane compares its LIVE release commit against the target
# commit over its own path filters. A landing-only copy edit never disturbs the API
# or Demo; a no-op change deploys nothing.
#
# Ordering: api -> demo -> landing, SEQUENTIALLY. The API releases before a dependent
# Demo change so the frontend never calls a backend missing its capabilities; lanes
# never run concurrently, so on a 2-core/4GB box at most ONE transient duplicate
# instance exists at a time, and concurrent lanes can never corrupt the shared
# release pool (one pool, one lane — the prior corruption class).
#
# Paired slots (#843): every deployable has two fixed, known-in-advance loopback
# ports; the nginx include under /etc/nginx/juli/ is the single source of truth for
# which is live, and the deploy never has to discover state:
#     api      8000 / 8020     /etc/nginx/juli/api-upstream.conf
#     demo     3001 / 3021     /etc/nginx/juli/demo-upstream.conf
#     landing  3007 / 3027     /etc/nginx/juli/landing-upstream.conf
# Each lane gets candidate verification before traffic moves, a graceful cutover,
# and automatic rollback (#840 pattern). The Demo lane delegates to the proven
# deploy-demo-release.sh; API and Landing implement the same pattern here.
#
# API verification asserts core route RESPONSE SHAPE, not only status (#843 AC):
# /health must be JSON with status=="ok", and /v1/demo/analytics must carry
# computed_at plus the five ADR-044 KPI keys.
#
# Release record (#844): every run appends step results AS THEY HAPPEN to
# ~/releases/records/deploy-<utc>-<short>.json. Only observed outcomes are written —
# there is no default and no assumed success; a step that never ran is absent.
#
# Migrations are applied ONCE, before any candidate starts (US-24), and only after
# the additive-only gate (#834) accepts them. They are never reverted by rollback.
set -euo pipefail

CANONICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
RECORDS_DIR="${RECORDS_DIR:-${RELEASES_ROOT}/records}"
NGINX_UPSTREAM_DIR="${NGINX_UPSTREAM_DIR:-/etc/nginx/juli}"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
CANDIDATE_TIMEOUT_SECS="${CANDIDATE_TIMEOUT_SECS:-120}"
PUBLIC_CHECK_TIMEOUT_SECS="${PUBLIC_CHECK_TIMEOUT_SECS:-45}"
API_ENV_FILE="${API_ENV_FILE:-/etc/juli/api.env}"
VERIFY_HARNESS="${CANONICAL_ROOT}/infra/scripts/verify-release-assets.sh"

# shellcheck source=infra/scripts/lib/prune-releases.sh
source "${CANONICAL_ROOT}/infra/scripts/lib/prune-releases.sh"

log()  { printf '\n== %s ==\n' "$*"; }
note() { printf '   %s\n' "$*"; }
die()  { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

http_code() {
    local code
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$1" 2>/dev/null)"
    echo "${code:-000}"
}

# --------------------------------------------------------------------------------------
# Lane configuration — fixed and known in advance; the deploy discovers nothing.
# --------------------------------------------------------------------------------------

LANE_ORDER="api demo landing"

lane_ports()    { case "$1" in api) echo "8000 8020" ;; demo) echo "3001 3021" ;; landing) echo "3007 3027" ;; *) return 1 ;; esac; }
lane_upstream() { echo "${NGINX_UPSTREAM_DIR}/$1-upstream.conf"; }
lane_upstream_name() { case "$1" in api) echo juli_api ;; demo) echo juli_demo ;; landing) echo juli_landing ;; *) return 1 ;; esac; }
lane_current()  { case "$1" in api) echo "${RELEASES_ROOT}/current" ;; demo) echo "${RELEASES_ROOT}/demo-current" ;; landing) echo "${RELEASES_ROOT}/landing-current" ;; *) return 1 ;; esac; }
lane_public_url() { case "$1" in api) echo "https://api.app-juli.com/health" ;; demo) echo "https://demo.app-juli.com/decisions" ;; landing) echo "https://app-juli.com/" ;; *) return 1 ;; esac; }

# Path filters. packages/ feeds both Next apps; backend + migrations + requirements
# feed the API. Filters are prefixes matched against `git diff --name-only`.
lane_path_filters() {
    case "$1" in
        api)     printf '%s\n' backend/ requirements.txt infra/systemd/juli-api.service ;;
        demo)    printf '%s\n' apps/demo/ packages/ pnpm-lock.yaml ;;
        landing) printf '%s\n' apps/landing/ packages/ pnpm-lock.yaml ;;
        *) return 1 ;;
    esac
}

# The commit a lane is LIVE on, read from its *current symlink's worktree. A lane with
# no deployment yet reports nothing and is treated as changed (first deploy).
lane_live_commit() {
    local link target
    link="$(lane_current "$1")"
    target="$(readlink -f "${link}" 2>/dev/null || true)"
    [ -n "${target}" ] && [ -d "${target}" ] || return 1
    git -C "${target}" rev-parse HEAD 2>/dev/null
}

# Whether a lane changed between its live commit and the target. Errors are treated
# as changed, never as "nothing to do" — a vacuous skip is how a stale release hides.
lane_changed() {
    local lane="$1" target_sha="$2" live diff filter matched
    live="$(lane_live_commit "${lane}" || true)"
    if [ -z "${live}" ]; then
        note "${lane}: no live release found — treating as changed (first deploy)" >&2
        return 0
    fi
    if [ "${live}" = "${target_sha}" ]; then
        return 1
    fi
    if ! diff="$(git -C "${CANONICAL_ROOT}" diff --name-only "${live}" "${target_sha}" 2>/dev/null)"; then
        note "${lane}: cannot diff ${live}..${target_sha} — treating as changed" >&2
        return 0
    fi
    matched=1
    while IFS= read -r filter; do
        if printf '%s\n' "${diff}" | grep -q "^${filter}"; then
            matched=0
            break
        fi
    done < <(lane_path_filters "${lane}")
    return "${matched}"
}

# --------------------------------------------------------------------------------------
# The release record (#844): only observed outcomes, appended as they happen.
# --------------------------------------------------------------------------------------

RECORD_FILE=""

record_open() {
    local sha="$1" short="$2"
    mkdir -p "${RECORDS_DIR}"
    RECORD_FILE="${RECORDS_DIR}/deploy-$(date -u +%Y%m%dT%H%M%SZ)-${short}.json"
    printf '{"commit": "%s", "started_at": "%s", "steps": [\n' \
        "${sha}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "${RECORD_FILE}"
}

# record_step <lane> <step> <result> [detail] — result is what the check RETURNED,
# passed in by the caller at the moment it observed it. There is no default arg on
# purpose: an unobserved outcome cannot be recorded.
record_step() {
    local lane="$1" step="$2" result="$3" detail="${4:-}"
    [ -n "${RECORD_FILE}" ] || return 0
    python3 - "$RECORD_FILE" "$lane" "$step" "$result" "$detail" <<'PY'
import json, sys
path, lane, step, result, detail = sys.argv[1:6]
entry = {"lane": lane, "step": step, "result": result, "at": __import__("datetime").datetime.now(__import__("datetime").UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
if detail:
    entry["detail"] = detail
with open(path, "a") as fh:
    fh.write(json.dumps(entry) + ",\n")
PY
}

record_close() {
    local outcome="$1"
    [ -n "${RECORD_FILE}" ] || return 0
    printf '{"lane": "-", "step": "deploy", "result": "%s", "at": "%s"}\n]}\n' \
        "${outcome}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "${RECORD_FILE}"
    note "release record: ${RECORD_FILE}"
}

# --------------------------------------------------------------------------------------
# Shared slot mechanics (#843) — the #839/#840 pattern, parameterized by lane.
# --------------------------------------------------------------------------------------

live_port_of() {
    local conf
    conf="$(lane_upstream "$1")"
    [ -f "${conf}" ] || { echo "FAIL: ${conf} missing — run provision-nginx.sh first" >&2; return 1; }
    awk 'match($0, /server[[:space:]]+127\.0\.0\.1:[0-9]+;/) {
        s = substr($0, RSTART, RLENGTH); sub(/.*:/, "", s); sub(/;/, "", s); print s; exit }' "${conf}"
}

peer_port_of() {
    local lane="$1" live="$2" a b
    read -r a b <<<"$(lane_ports "${lane}")"
    case "${live}" in
        "${a}") echo "${b}" ;;
        "${b}") echo "${a}" ;;
        *) echo "FAIL: live port ${live} is not in ${lane}'s pair (${a}/${b})" >&2; return 1 ;;
    esac
}

render_upstream() {
    local lane="$1" port="$2"
    case "${port}" in ''|*[!0-9]*) echo "FAIL: non-numeric port '${port}'" >&2; return 1 ;; esac
    cat <<EOF
# Generated by infra/scripts/deploy.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ). Do not edit.
# Single source of truth for which ${lane} instance is serving. The previous
# definition is retained beside it as .prev — restoring it and reloading is the undo.
upstream $(lane_upstream_name "${lane}") {
    server 127.0.0.1:${port};
    keepalive 16;
}
EOF
}

switch_upstream() {
    local lane="$1" port="$2" conf prev tmp
    conf="$(lane_upstream "${lane}")"
    prev="${conf}.prev"
    tmp="${conf}.tmp.$$"
    render_upstream "${lane}" "${port}" >"${tmp}" || { rm -f "${tmp}"; return 1; }
    cp -p "${conf}" "${prev}" || { rm -f "${tmp}"; return 1; }
    mv -f "${tmp}" "${conf}"
    if ! nginx -t >&2; then
        echo "FAIL: nginx rejected the new ${lane} upstream; restoring .prev" >&2
        cp -p "${prev}" "${conf}"
        nginx -t >&2 || echo "FAIL: restored config also rejected — fault is elsewhere" >&2
        return 1
    fi
    systemctl reload nginx
}


# Reboot durability: transient candidates do not survive a reboot; the durable unit
# must come back on the port nginx is pointed at, not its baked default.
write_runtime_env() {
    local lane="$1" port="$2" var file tmp
    case "${lane}" in
        api)     var=API_LIVE_PORT;     file=/etc/juli/api-runtime.env ;;
        landing) var=LANDING_LIVE_PORT; file=/etc/juli/landing-runtime.env ;;
        *) return 0 ;;
    esac
    mkdir -p "$(dirname "${file}")"
    tmp="${file}.tmp.$$"
    printf '# Written by deploy.sh (#843). Do not edit.\n%s=%s\n' "${var}" "${port}" > "${tmp}"
    mv -f "${tmp}" "${file}"
    install -m 0644 "${CANONICAL_ROOT}/infra/systemd/juli-${lane}.service" \
        "/etc/systemd/system/juli-${lane}.service"
    systemctl daemon-reload
}

rollback_lane() {
    local lane="$1" prev_port="$2"
    log "automatic rollback (${lane}) — returning traffic to :${prev_port}"
    switch_upstream "${lane}" "${prev_port}" || return 1
    write_runtime_env "${lane}" "${prev_port}"
    record_step "${lane}" "rollback" "restored_to_${prev_port}"
}

wait_2xx() {
    local url="$1" deadline=$((SECONDS + CANDIDATE_TIMEOUT_SECS)) code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        code="$(http_code "${url}")"
        [ "${#code}" -eq 3 ] && [ "${code#2}" != "${code}" ] && { echo "${code}"; return 0; }
        sleep 3
    done
    echo "${code}"
    return 1
}

public_check() {
    local url="$1" deadline=$((SECONDS + PUBLIC_CHECK_TIMEOUT_SECS)) code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        code="$(http_code "${url}")"
        [ "${#code}" -eq 3 ] && [ "${code#2}" != "${code}" ] && return 0
        sleep 3
    done
    echo "FAIL: public check ${url} did not pass (last HTTP ${code})" >&2
    return 1
}

# API core-route response SHAPE (#843 AC): a healthy process with a broken route — or a
# route returning HTML, or an envelope missing its keys — must fail verification.
verify_api_shape() {
    local base="$1"
    python3 - "$base" <<'PY'
import json, sys, urllib.request
base = sys.argv[1]
def get(path):
    req = urllib.request.Request(base + path, headers={"User-Agent": "juli-deploy-verify/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())
health = get("/health")
assert health.get("status") == "ok", f"/health shape wrong: {health!r}"
env = get("/v1/demo/analytics")
assert "computed_at" in env, "analytics envelope missing computed_at"
kpis = env.get("kpis") or {}
missing = {"gmv_tiktok", "aov", "ctor", "live_hours", "cancellation_rate"} - set(kpis)
assert not missing, f"analytics envelope missing KPIs: {sorted(missing)}"
print("PASS: API core routes carry the expected response shapes")
PY
}

# --------------------------------------------------------------------------------------
# Lanes
# --------------------------------------------------------------------------------------

ensure_release_worktree() {
    local sha="$1" release_dir="$2"
    if [ -d "${release_dir}" ]; then
        git -C "${release_dir}" fetch --depth 1 origin "${sha}" >&2 || true
        git -C "${release_dir}" checkout --force "${sha}" >&2
    else
        git -C "${CANONICAL_ROOT}" worktree add --force "${release_dir}" "${sha}" >&2
    fi
}

deploy_lane_api() {
    local sha="$1" release_dir="$2" live_port peer_port code
    live_port="$(live_port_of api)" || return 1
    peer_port="$(peer_port_of api "${live_port}")" || return 1
    log "api lane: live :${live_port}, candidate :${peer_port}"

    # Build the venv in the release dir (API artifacts stay server-built for now).
    python3 -m venv "${release_dir}/.venv"
    "${release_dir}/.venv/bin/pip" install -q --upgrade pip
    # -c pins to the exact versions CI tested (#921) — release_dir is a git
    # worktree checkout of this commit's sha, so backend/constraints.txt is
    # already present here; no separate artifact download needed for the API
    # lane (unlike demo/landing's prebuilt tarballs).
    "${release_dir}/.venv/bin/pip" install -q -r "${release_dir}/requirements.txt" -c "${release_dir}/backend/constraints.txt"
    "${release_dir}/.venv/bin/pip" install -q -e "${release_dir}/backend" -c "${release_dir}/backend/constraints.txt"
    record_step api build "completed"

    # Migrations: additive-gate + apply BEFORE the candidate starts. Never reverted.
    set -a; # shellcheck disable=SC1090
    source "${API_ENV_FILE}"; set +a
    RELEASE_DIR="${release_dir}" API_ENV_FILE="${API_ENV_FILE}" \
        "${CANONICAL_ROOT}/infra/scripts/safe-alembic-upgrade.sh"
    record_step api migrations "applied"

    systemctl stop "juli-api-candidate-${peer_port}" >/dev/null 2>&1 || true
    systemctl reset-failed "juli-api-candidate-${peer_port}" >/dev/null 2>&1 || true
    systemd-run --unit="juli-api-candidate-${peer_port}" --collect \
        --property=Type=simple \
        --property=WorkingDirectory="${release_dir}" \
        --property=EnvironmentFile="${API_ENV_FILE}" \
        --property=Restart=no \
        "${release_dir}/.venv/bin/uvicorn" juli_backend.api.main:app \
        --host 127.0.0.1 --port "${peer_port}" --workers 1 >&2
    if ! code="$(wait_2xx "http://127.0.0.1:${peer_port}/health")"; then
        record_step api candidate "failed" "never ready (HTTP ${code})"
        systemctl stop "juli-api-candidate-${peer_port}" >/dev/null 2>&1 || true
        return 1
    fi
    record_step api candidate "ready" "HTTP ${code}"

    if ! verify_api_shape "http://127.0.0.1:${peer_port}"; then
        record_step api verify_shape "failed"
        systemctl stop "juli-api-candidate-${peer_port}" >/dev/null 2>&1 || true
        return 1
    fi
    record_step api verify_shape "passed"

    switch_upstream api "${peer_port}" || { record_step api cutover "refused"; return 1; }
    record_step api cutover "switched_to_${peer_port}"
    write_runtime_env api "${peer_port}"
    ln -sfn "${release_dir}" "${RELEASES_ROOT}/current.tmp"
    mv -Tf "${RELEASES_ROOT}/current.tmp" "$(lane_current api)"

    if ! public_check "$(lane_public_url api)"; then
        record_step api public_check "failed"
        rollback_lane api "${live_port}"
        return 1
    fi
    record_step api public_check "passed"
    # Celery workers follow the API release (they import the same tree).
    for unit in juli-celery-worker juli-celery-beat; do
        if systemctl cat "${unit}" >/dev/null 2>&1; then
            systemctl restart "${unit}"
        else
            echo "SKIP: ${unit} not installed on this host"
        fi
    done
    record_step api celery "restarted"
}

deploy_lane_demo() {
    local sha="$1"
    log "demo lane: delegating to deploy-demo-release.sh (the proven #838/#839/#840 lane)"
    if "${CANONICAL_ROOT}/infra/scripts/deploy-demo-release.sh" "${sha}"; then
        record_step demo deploy "completed"
    else
        record_step demo deploy "failed"
        return 1
    fi
}

# #841's artifact helpers, inlined when the per-app script retired (#844).
fetch_landing_artifact() {
    local sha="$1" short7="$2" dest_dir="$3"
    local name="juli-landing-${short7}" run_id="" tarball=""
    if [ -n "${LANDING_ARTIFACT_TARBALL:-}" ]; then
        echo "Using the operator-supplied artifact ${LANDING_ARTIFACT_TARBALL}" >&2
        printf '%s\n' "${LANDING_ARTIFACT_TARBALL}"
        return 0
    fi
    command -v gh >/dev/null 2>&1 || {
        echo "FAIL: gh is not installed; supply LANDING_ARTIFACT_TARBALL instead." >&2
        return 1
    }
    mkdir -p "${dest_dir}"
    echo "Locating the release.yml run for ${sha}" >&2
    run_id="$(gh run list --commit "${sha}" --workflow release.yml --limit 20 \
        --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
    [ -n "${run_id}" ] || {
        echo "FAIL: no release.yml run found for ${sha}; CI has not published ${name}." >&2
        return 1
    }
    echo "Downloading artifact ${name} from run ${run_id}" >&2
    gh run download "${run_id}" --name "${name}" --dir "${dest_dir}" >&2 || {
        echo "FAIL: artifact ${name} is not attached to run ${run_id}." >&2
        echo "      Deploy a commit whose release.yml run is green, or supply" >&2
        echo "      LANDING_ARTIFACT_TARBALL=/path/to/${name}.tar.gz" >&2
        return 1
    }
    tarball="$(find "${dest_dir}" -maxdepth 2 -name '*.tar.gz' -type f 2>/dev/null | head -n 1)"
    [ -n "${tarball}" ] || {
        echo "FAIL: downloaded ${name} but found no tarball under ${dest_dir}." >&2
        return 1
    }
    printf '%s\n' "${tarball}"
}

place_landing_artifact() {
    local tarball="$1" release_dir="$2" expected_sha="$3"
    local stage_root stage recorded dest
    [ -f "${tarball}" ] || {
        echo "FAIL: release artifact tarball not found: ${tarball}" >&2
        return 1
    }
    stage_root="$(mktemp -d)" || return 1
    tar -xzf "${tarball}" -C "${stage_root}" || {
        echo "FAIL: could not extract ${tarball}" >&2
        rm -rf "${stage_root}"
        return 1
    }
    stage="$(find "${stage_root}" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
    [ -n "${stage}" ] && [ -d "${stage}" ] || {
        echo "FAIL: ${tarball} contained no artifact directory" >&2
        rm -rf "${stage_root}"
        return 1
    }
    [ -f "${stage}/release-artifact.json" ] || {
        echo "FAIL: ${tarball} carries no release-artifact.json — not an ADR-058 artifact" >&2
        rm -rf "${stage_root}"
        return 1
    }
    recorded="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' \
        "${stage}/release-artifact.json" 2>/dev/null || true)"
    if [ "${recorded}" != "${expected_sha}" ]; then
        echo "FAIL: artifact records commit ${recorded}, not ${expected_sha} being deployed." >&2
        rm -rf "${stage_root}"
        return 1
    fi
    dest="${release_dir}/apps/landing"
    rm -rf "${dest:?}"
    mkdir -p "$(dirname "${dest}")"
    mv "${stage}" "${dest}" || {
        rm -rf "${stage_root}"
        return 1
    }
    rm -rf "${stage_root}"
    [ -x "${dest}/node_modules/.bin/next" ] || {
        echo "FAIL: placed artifact has no runnable next binary at ${dest}" >&2
        return 1
    }
}

deploy_lane_landing() {
    local sha="$1" release_dir="$2" live_port peer_port code short7="${sha:0:7}"
    live_port="$(live_port_of landing)" || return 1
    peer_port="$(peer_port_of landing "${live_port}")" || return 1
    log "landing lane: live :${live_port}, candidate :${peer_port}"

    local artifact_dir="${HOME}/.cache/juli-release-artifacts/landing-${short7}" tarball
    rm -rf "${artifact_dir:?}"
    tarball="$(fetch_landing_artifact "${sha}" "${short7}" "${artifact_dir}")" || {
        record_step landing artifact "failed" "not published for ${short7}"
        return 1
    }
    place_landing_artifact "${tarball}" "${release_dir}" "${sha}" || {
        record_step landing artifact "failed" "placement refused"
        return 1
    }
    record_step landing artifact "placed"

    systemctl stop "juli-landing-candidate-${peer_port}" >/dev/null 2>&1 || true
    systemctl reset-failed "juli-landing-candidate-${peer_port}" >/dev/null 2>&1 || true
    systemd-run --unit="juli-landing-candidate-${peer_port}" --collect \
        --property=Type=simple \
        --property=WorkingDirectory="${release_dir}/apps/landing" \
        --property=Restart=no \
        "${release_dir}/apps/landing/node_modules/.bin/next" start \
        --port "${peer_port}" --hostname 127.0.0.1 >&2
    if ! code="$(wait_2xx "http://127.0.0.1:${peer_port}/")"; then
        record_step landing candidate "failed" "never ready (HTTP ${code})"
        systemctl stop "juli-landing-candidate-${peer_port}" >/dev/null 2>&1 || true
        return 1
    fi
    record_step landing candidate "ready" "HTTP ${code}"

    if ! "${VERIFY_HARNESS}" --base-url "http://127.0.0.1:${peer_port}" --route /; then
        record_step landing verify_assets "failed"
        systemctl stop "juli-landing-candidate-${peer_port}" >/dev/null 2>&1 || true
        return 1
    fi
    record_step landing verify_assets "passed"

    switch_upstream landing "${peer_port}" || { record_step landing cutover "refused"; return 1; }
    record_step landing cutover "switched_to_${peer_port}"
    write_runtime_env landing "${peer_port}"
    ln -sfn "${release_dir}" "${RELEASES_ROOT}/landing-current.tmp"
    mv -Tf "${RELEASES_ROOT}/landing-current.tmp" "$(lane_current landing)"

    if ! public_check "$(lane_public_url landing)"; then
        record_step landing public_check "failed"
        rollback_lane landing "${live_port}"
        return 1
    fi
    record_step landing public_check "passed"
}

# --------------------------------------------------------------------------------------

main() {
    local sha="${1:-}" short_sha release_dir lanes="" lane failed=""
    if [ -z "${sha}" ]; then
        git -C "${CANONICAL_ROOT}" fetch origin main
        sha="$(git -C "${CANONICAL_ROOT}" rev-parse origin/main)"
    fi
    short_sha="$(git -C "${CANONICAL_ROOT}" rev-parse --short "${sha}")"
    release_dir="${RELEASES_ROOT}/${short_sha}"

    log "Juli deploy (#844): ${sha} (${short_sha})"
    for lane in ${LANE_ORDER}; do
        if lane_changed "${lane}" "${sha}"; then
            lanes="${lanes} ${lane}"
        else
            note "${lane}: unchanged — skipped"
        fi
    done
    if [ -z "${lanes// /}" ]; then
        note "no deployable changed — nothing to deploy"
        exit 0
    fi
    note "lanes to run (in order):${lanes}"

    record_open "${sha}" "${short_sha}"
    ensure_release_worktree "${sha}" "${release_dir}"

    for lane in ${lanes}; do
        case "${lane}" in
            api)     deploy_lane_api "${sha}" "${release_dir}" || failed="${failed} api" ;;
            demo)    deploy_lane_demo "${sha}" || failed="${failed} demo" ;;
            landing) deploy_lane_landing "${sha}" "${release_dir}" || failed="${failed} landing" ;;
        esac
        if [ -n "${failed}" ]; then
            # A failed lane stops the run: a Demo depending on new API capabilities
            # must not ship over a failed API lane.
            break
        fi
    done

    if [ -n "${failed}" ]; then
        record_close "failed:${failed// /}"
        die "deploy failed in lane(s):${failed} — see the release record"
    fi
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha}" "${release_dir}" \
        >> "${RELEASES_ROOT}/deploy-history.log"
    prune_release_worktrees "${CANONICAL_ROOT}" "${RELEASES_ROOT}" "${KEEP_RELEASES}" "${release_dir}"
    record_close "completed"
    log "deploy complete: ${sha}"
}

if [ "${DEPLOY_SOURCE_ONLY:-0}" != "1" ]; then
    main "$@"
fi
