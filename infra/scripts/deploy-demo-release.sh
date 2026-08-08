#!/usr/bin/env bash
# Continuous delivery for Demo: candidate-first (#838) with a graceful cutover (#839).
# Slices P0-DEL-CANDIDATE and P0-DEL-SWITCH of PRD #820.
#
# WHAT CHANGED AND WHY (#839) — THE GRACEFUL SWITCH
# -------------------------------------------------
# Cutover used to be `mv -Tf demo-current` followed by `systemctl restart juli-demo`.
# Nginx proxied straight at 127.0.0.1:3001, so that restart WAS the error window: every
# in-flight and arriving request failed until the process came back.
#
# There is no restart in the cutover path any more. Nginx proxies to an upstream whose
# definition the deployment owns:
#
#   /etc/nginx/juli/demo-upstream.conf        what is serving RIGHT NOW (source of truth)
#   /etc/nginx/juli/demo-upstream.conf.prev   the immediately previous definition (the undo)
#
# The Demo lane alternates between two loopback ports, 127.0.0.1:3001 and 127.0.0.1:3021.
# The live definition names one of them; the candidate is started on the other. Once the
# candidate has passed verification it is ALREADY answering, so cutover is:
#
#   render -> stage to a temp file -> retain the current definition as .prev
#          -> mv -Tf into place -> nginx -t -> systemctl reload nginx
#
# reload, never restart: reload lets nginx finish in-flight requests on the old worker
# processes. And because the upstream is only ever repointed at a process that is already
# answering, no request can observe an unavailable upstream at any instant of a release.
# If `nginx -t` refuses the new definition, nothing is reloaded — the configuration nginx
# already loaded keeps serving — the retained definition is put back, and the deploy exits
# non-zero.
#
# ONE-TIME PROVISIONING: `sudo ./infra/scripts/provision-nginx.sh` must have installed
# /etc/nginx/juli/demo-upstream.conf before the first deploy that uses the indirection.
# This script refuses to create it: doing so would hide that nginx never had it.
#
# THE PREVIOUS INSTANCE IS NOT STOPPED. It keeps running on the port it had, which is what
# makes .prev a real undo — restoring that file and reloading returns traffic instantly.
# It is stopped at the START of the NEXT deploy (free_candidate_port), when its port is
# needed and it has long since drained. Automatic post-cutover rollback is #840.
#
# WHAT CHANGED AND WHY (#838) — CANDIDATE FIRST
# ---------------------------------------------
# This script used to mutate first and verify second: it flipped ~/releases/demo-current,
# restarted juli-demo, and only then health-checked. By the time a check failed, the
# broken release was already public. The order is now inverted:
#
#   migration gate  ->  place the CI artifact  ->  start a CANDIDATE on 127.0.0.1:3021
#                   ->  run the #833 verification harness against the candidate
#                   ->  only on a pass: stop the candidate and cut over
#
# The candidate binds 127.0.0.1 only. Spike #835 confirmed on the real VPS that a
# loopback-bound instance does not answer on the external interface, so no nginx, DNS, or
# firewall change is needed to keep it private — the bind address is the whole mechanism.
#
# On ANY failure after the candidate starts, fail_candidate stops the candidate and exits
# non-zero. The live instance is never restarted, demo-current is never repointed, and no
# visitor ever sees the release. Post-cutover rollback is #840.
#
# NEVER PRUNE ON A FAILURE PATH. ~/releases is a single pool shared by every deploy lane,
# and a prune has previously destroyed the live release. Pruning runs only after a
# successful cutover.
#
# WHERE THE BUILD COMES FROM (#837, ADR-058)
# ------------------------------------------
# Nothing is compiled here. CI (.github/workflows/release.yml, job app-release-artifact)
# publishes juli-demo-<short-sha> containing .next, public, package.json, a
# `pnpm deploy --prod` dependency tree, and release-artifact.json carrying the full
# 40-char commit. This script downloads that artifact for the target commit and overlays
# it onto the release worktree's apps/demo, refusing any artifact whose recorded commit is
# not the commit being deployed.
#
# Release model:
#   ~/Juli-AI-v2              canonical clone; source of truth for `git worktree add`
#   ~/releases/<short-sha>/   one worktree per release (shared with App Review deploys)
#   ~/releases/demo-current   symlink to the active Demo release
#   ~/releases/demo-deploy-history.log   append-only log for Demo rollback
#
# Health probes (the pair alternates, so which port is which swaps every release):
#   candidate, before any traffic moves: http://127.0.0.1:3021/decisions
#   live, seeded by provisioning:        http://127.0.0.1:3001/decisions must return 2xx
#
# Usage (on the VPS, as root):
#   cd ~/Juli-AI-v2 && git fetch origin main && git checkout main && git pull
#   ./infra/scripts/deploy-demo-release.sh <sha>
#   ./infra/scripts/deploy-demo-release.sh                 # defaults to origin/main HEAD
#
# If `gh` is not authenticated on the server, download the artifact elsewhere and point at
# the tarball directly:
#   DEMO_ARTIFACT_TARBALL=/root/juli-demo-abc1234.tar.gz ./infra/scripts/deploy-demo-release.sh <sha>
#
# Env overrides:
#   KEEP_DEMO_RELEASES (3)          releases kept per lane after a successful cutover
#   HEALTH_TIMEOUT_SECS (60)        post-cutover health probe budget
#   DEMO_CANDIDATE_PORT (3021)      fallback candidate port; normally derived as the peer
#                                   of whatever the live upstream definition names
#   DEMO_CANDIDATE_UNIT             transient systemd unit prefix (suffixed with the port)
#   DEMO_UPSTREAM_CONF              the live upstream definition nginx includes
#                                   (/etc/nginx/juli/demo-upstream.conf)
#   DEMO_RUNTIME_ENV                where the live port is recorded for juli-demo.service
#                                   (/etc/juli/demo-runtime.env)
#   CANDIDATE_TIMEOUT_SECS (120)    candidate readiness budget
#   DEMO_CANDIDATE_ROUTES           HTML routes the harness verifies (default "/ /decisions")
#   DEMO_CANDIDATE_API_BASE_URL     set to also run --api-check specs against an API
#   DEMO_CANDIDATE_API_CHECKS       space-separated PATH:key1,key2 specs. Empty by default:
#                                   apps/demo is mock-mode and exposes no JSON API, so
#                                   there is no API path to assert here. The wiring exists
#                                   so a deployable that does have one gets shape checks
#                                   (not merely status) for free.
#   DEMO_ARTIFACT_TARBALL           use this local tarball instead of downloading
#   ARTIFACT_CACHE_ROOT             where artifacts are downloaded (~/.cache/juli-release-artifacts)
#   DEMO_MIGRATION_GATE_BASE_SHA    baseline commit for pending-migration discovery
#   DEMO_DEPLOY_SOURCE_ONLY=1       define the functions and return; deploy nothing
#                                   (this is how tests/unit/test_demo_candidate_verification.py
#                                   exercises the functions for real)
set -euo pipefail

CANONICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
DEMO_CURRENT="${RELEASES_ROOT}/demo-current"
HISTORY_LOG="${RELEASES_ROOT}/demo-deploy-history.log"
KEEP_DEMO_RELEASES="${KEEP_DEMO_RELEASES:-3}"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
DEMO_PORT="3001"

# The Demo lane alternates between these two loopback ports. Whichever the live upstream
# definition names is serving; the other is where the next candidate is started.
DEMO_PORT_A="3001"
DEMO_PORT_B="3021"

# The upstream indirection this deploy owns (#839).
NGINX_UPSTREAM_DIR="${NGINX_UPSTREAM_DIR:-/etc/nginx/juli}"
DEMO_UPSTREAM_CONF="${DEMO_UPSTREAM_CONF:-${NGINX_UPSTREAM_DIR}/demo-upstream.conf}"
DEMO_UPSTREAM_PREV="${DEMO_UPSTREAM_CONF}.prev"
DEMO_UPSTREAM_NAME="juli_demo"
DEMO_RUNTIME_ENV="${DEMO_RUNTIME_ENV:-/etc/juli/demo-runtime.env}"

# Resolved from the live upstream definition in main(); the seed default is only a
# fallback for library mode and for reporting before anything has been read.
LIVE_PORT="${DEMO_PORT}"

DEMO_CANDIDATE_PORT="${DEMO_CANDIDATE_PORT:-3021}"
DEMO_CANDIDATE_UNIT="${DEMO_CANDIDATE_UNIT:-juli-demo-candidate}"
# The unit name is suffixed with the candidate's port in main(). After #839 a verified
# candidate is PROMOTED to live rather than stopped, so the previous deploy's instance is
# still running and a fixed unit name would collide with it.
CANDIDATE_UNIT="${DEMO_CANDIDATE_UNIT}"
CANDIDATE_TIMEOUT_SECS="${CANDIDATE_TIMEOUT_SECS:-120}"
DEMO_CANDIDATE_ROUTES="${DEMO_CANDIDATE_ROUTES:-/ /decisions}"
DEMO_CANDIDATE_API_BASE_URL="${DEMO_CANDIDATE_API_BASE_URL:-}"
DEMO_CANDIDATE_API_CHECKS="${DEMO_CANDIDATE_API_CHECKS:-}"

VERIFY_HARNESS="${CANONICAL_ROOT}/infra/scripts/verify-release-assets.sh"
MIGRATION_GATE="${CANONICAL_ROOT}/infra/scripts/migration_additive_gate.py"
MIGRATIONS_VERSIONS_REL="backend/src/juli_backend/database/migrations/versions"

# Downloaded artifacts are staged OUTSIDE ~/releases on purpose: that directory is a pool
# of release worktrees shared by every deploy lane, and nothing but a worktree, a *current
# symlink, or a history log belongs in it.
ARTIFACT_CACHE_ROOT="${ARTIFACT_CACHE_ROOT:-$HOME/.cache/juli-release-artifacts}"

# shellcheck source=infra/scripts/lib/prune-releases.sh
source "${CANONICAL_ROOT}/infra/scripts/lib/prune-releases.sh"

log()  { printf '\n== %s ==\n' "$*"; }
note() { printf '   %s\n' "$*"; }
die()  { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

# curl already prints 000 on a connection failure; `|| echo 000` would concatenate onto
# it and report "000000", so capture and default instead (same fix as the #835 spike).
http_code() {
    local code
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$1" 2>/dev/null)"
    echo "${code:-000}"
}

# What the operator needs to see on every failure: that live is still answering and that
# demo-current still points where it did before this run.
report_live_state() {
    local code target
    code="$(http_code "http://127.0.0.1:${LIVE_PORT}/decisions")"
    target="$(readlink -f "${DEMO_CURRENT}" 2>/dev/null || echo MISSING)"
    printf '   live Demo :%s/decisions -> HTTP %s\n' "${LIVE_PORT}" "${code}"
    printf '   demo-current still -> %s (not repointed by this run)\n' "${target}"
}

# ---------------------------------------------------------------------------------------
# The owned upstream indirection (#839)
# ---------------------------------------------------------------------------------------

# Atomic replacement, never an in-place edit: a file nginx reads half-written is a live
# outage. GNU -T refuses to descend into DEST when DEST is a directory, which is what
# stops a replacement silently becoming a move-inside; the explicit guard gives the same
# protection where mv has no -T (BSD/macOS, i.e. the contract tests). Onto an existing
# regular file this is a single rename(2) either way.
atomic_replace() {
    local src="$1" dest="$2"
    if [ -d "${dest}" ]; then
        echo "FAIL: ${dest} is a directory; refusing to replace it" >&2
        return 1
    fi
    if mv -Tf "${src}" "${dest}" 2>/dev/null; then
        return 0
    fi
    mv -f "${src}" "${dest}"
}

# The definition that will be written. One place, so what is generated cannot drift from
# what is asserted. Anything that is not a bare in-range port number is refused: this
# string ends up inside the live nginx configuration, and a malformed switch must never be
# able to take the site down.
render_demo_upstream() {
    local port="$1"
    case "${port}" in
        '' | *[!0-9]*)
            echo "FAIL: refusing to render an upstream for non-numeric port '${port}'" >&2
            return 1
            ;;
    esac
    if [ "${port}" -lt 1 ] || [ "${port}" -gt 65535 ]; then
        echo "FAIL: upstream port ${port} is out of range" >&2
        return 1
    fi
    cat <<EOF
# Generated by infra/scripts/deploy-demo-release.sh (#839) on $(date -u +%Y-%m-%dT%H:%M:%SZ).
# Do not edit by hand. This file is the single source of truth for which Demo instance is
# serving demo.app-juli.com. The immediately previous definition is retained beside it at
# ${DEMO_UPSTREAM_PREV} — restoring that file and reloading nginx is the undo.
upstream ${DEMO_UPSTREAM_NAME} {
    server 127.0.0.1:${port};
    keepalive 16;
}
EOF
}

# Which Demo instance is serving, read from the live definition itself. There is no
# fallback on purpose: guessing here would start a candidate on the port that is already
# serving, which would take the site down.
live_upstream_port() {
    local port
    if [ ! -f "${DEMO_UPSTREAM_CONF}" ]; then
        echo "FAIL: ${DEMO_UPSTREAM_CONF} does not exist, so nothing can be read about what" >&2
        echo "      is serving. Run the one-time step 'sudo ./infra/scripts/provision-nginx.sh'" >&2
        echo "      to install the upstream indirection, then re-run this deploy." >&2
        return 1
    fi
    port="$(awk 'match($0, /server[[:space:]]+127\.0\.0\.1:[0-9]+;/) {
            s = substr($0, RSTART, RLENGTH); sub(/.*:/, "", s); sub(/;/, "", s); print s; exit
        }' "${DEMO_UPSTREAM_CONF}")"
    if [ -z "${port}" ]; then
        echo "FAIL: ${DEMO_UPSTREAM_CONF} names no 127.0.0.1 server directive." >&2
        return 1
    fi
    printf '%s\n' "${port}"
}

# The pair member that is not live — where the next candidate goes.
demo_peer_port() {
    local live="$1"
    case "${live}" in
        "${DEMO_PORT_A}") printf '%s\n' "${DEMO_PORT_B}" ;;
        "${DEMO_PORT_B}") printf '%s\n' "${DEMO_PORT_A}" ;;
        *)
            echo "FAIL: the live upstream names port '${live}', which is not a member of the" >&2
            echo "      Demo port pair (${DEMO_PORT_A}/${DEMO_PORT_B}). Refusing to guess where" >&2
            echo "      to start a candidate." >&2
            return 1
            ;;
    esac
}

# The cutover itself. Atomic replacement, then validation, then a GRACEFUL reload.
#
#   * The previous definition is retained as .prev BEFORE anything moves, so a rejected
#     configuration can be put back and #840 has an undo to automate.
#   * nginx is reloaded only AFTER `nginx -t` passes, so an invalid configuration is
#     rejected while the configuration nginx already loaded keeps serving, untouched.
#   * reload, never restart: reload finishes in-flight requests on the old workers.
switch_demo_upstream() {
    local port="$1" tmp prev_tmp restore_tmp

    if [ ! -f "${DEMO_UPSTREAM_CONF}" ]; then
        echo "FAIL: ${DEMO_UPSTREAM_CONF} is missing, so demo.app-juli.com is not routed" >&2
        echo "      through the upstream indirection yet. Run the one-time step" >&2
        echo "      'sudo ./infra/scripts/provision-nginx.sh' and re-run this deploy." >&2
        echo "      Creating it here would hide that nginx never had it." >&2
        return 1
    fi

    tmp="${DEMO_UPSTREAM_CONF}.tmp.$$"
    prev_tmp="${DEMO_UPSTREAM_PREV}.tmp.$$"
    if ! render_demo_upstream "${port}" >"${tmp}"; then
        rm -f "${tmp}"
        return 1
    fi

    if ! cp -p "${DEMO_UPSTREAM_CONF}" "${prev_tmp}"; then
        echo "FAIL: could not retain the current definition; refusing to switch without an undo." >&2
        rm -f "${tmp}" "${prev_tmp}"
        return 1
    fi
    if ! atomic_replace "${prev_tmp}" "${DEMO_UPSTREAM_PREV}"; then
        rm -f "${tmp}" "${prev_tmp}"
        return 1
    fi

    if ! atomic_replace "${tmp}" "${DEMO_UPSTREAM_CONF}"; then
        rm -f "${tmp}"
        return 1
    fi

    if ! nginx -t >&2; then
        echo "FAIL: nginx rejected the configuration carrying the new upstream definition." >&2
        echo "      No reload was attempted, so the configuration nginx already loaded is" >&2
        echo "      still serving, unchanged. Restoring ${DEMO_UPSTREAM_PREV}." >&2
        restore_tmp="${DEMO_UPSTREAM_CONF}.restore.$$"
        if cp -p "${DEMO_UPSTREAM_PREV}" "${restore_tmp}" &&
            atomic_replace "${restore_tmp}" "${DEMO_UPSTREAM_CONF}"; then
            echo "      Restored; on-disk and loaded configuration agree again." >&2
        else
            rm -f "${restore_tmp}"
            echo "FAIL: could not restore ${DEMO_UPSTREAM_PREV} onto ${DEMO_UPSTREAM_CONF}." >&2
            echo "      Nothing was reloaded, so the site is still serving, but the file on" >&2
            echo "      disk no longer matches it. Fix it before any nginx reload." >&2
        fi
        nginx -t >&2 ||
            echo "FAIL: nginx rejects the restored configuration too — the fault is elsewhere in /etc/nginx." >&2
        return 1
    fi

    systemctl reload nginx
}

# Record the live port for juli-demo.service. Transient candidate units do not survive a
# reboot; the durable unit does, and it must come back on the port nginx is pointed at
# rather than on whatever used to be live.
write_demo_runtime_env() {
    local port="$1" tmp
    mkdir -p "$(dirname "${DEMO_RUNTIME_ENV}")" || return 1
    tmp="${DEMO_RUNTIME_ENV}.tmp.$$"
    {
        printf '# Written by infra/scripts/deploy-demo-release.sh (#839). Do not edit by hand.\n'
        printf '# The loopback port %s is pointed at.\n' "${DEMO_UPSTREAM_CONF}"
        printf 'DEMO_LIVE_PORT=%s\n' "${port}"
    } >"${tmp}" || {
        rm -f "${tmp}"
        return 1
    }
    atomic_replace "${tmp}" "${DEMO_RUNTIME_ENV}"
}

# Free the port the next candidate needs. By construction that port is NOT the live one —
# the live port is read from the upstream definition and the candidate takes its peer — so
# whatever holds it is a drained previous instance, never something serving public traffic.
# Two things can hold it: a candidate promoted by an earlier deploy, or juli-demo.service.
free_candidate_port() {
    local port="$1"
    systemctl stop "${DEMO_CANDIDATE_UNIT}-${port}" >/dev/null 2>&1 || true
    systemctl reset-failed "${DEMO_CANDIDATE_UNIT}-${port}" >/dev/null 2>&1 || true
    if [ "$(http_code "http://127.0.0.1:${port}/decisions")" != "000" ]; then
        note "something still answers on :${port} — stopping juli-demo, which is not serving"
        note "public traffic (public traffic is on :${LIVE_PORT})"
        systemctl stop juli-demo >/dev/null 2>&1 || true
    fi
}

# ---------------------------------------------------------------------------------------
# The candidate
# ---------------------------------------------------------------------------------------

# The one place a Demo process is ever spawned. Kept as a separate function so the argv
# under test is literally the argv systemd-run launches — the loopback bind cannot drift
# away from what the tests assert.
demo_candidate_argv() {
    local release_dir="$1" port="$2"
    printf '%s\n' \
        "${release_dir}/apps/demo/node_modules/.bin/next" \
        "start" \
        "--port" "${port}" \
        "--hostname" "127.0.0.1"
}

start_candidate() {
    local release_dir="$1" port="$2"
    local argv=() line
    while IFS= read -r line; do
        argv+=("${line}")
    done < <(demo_candidate_argv "${release_dir}" "${port}")

    systemctl reset-failed "${CANDIDATE_UNIT}" >/dev/null 2>&1 || true
    systemd-run --unit="${CANDIDATE_UNIT}" --collect \
        --property=Type=simple \
        --property=WorkingDirectory="${release_dir}/apps/demo" \
        --property=Restart=no \
        "${argv[@]}" >&2
}

stop_candidate() {
    systemctl stop "${CANDIDATE_UNIT}" >/dev/null 2>&1 || true
    systemctl reset-failed "${CANDIDATE_UNIT}" >/dev/null 2>&1 || true
}

dump_candidate_unit() {
    echo "-- ${CANDIDATE_UNIT} status --" >&2
    systemctl --no-pager --full status "${CANDIDATE_UNIT}" 2>&1 | head -20 >&2 || true
    echo "-- ${CANDIDATE_UNIT} logs --" >&2
    journalctl -u "${CANDIDATE_UNIT}" -n 60 --no-pager >&2 2>&1 || true
}

# Every failure after the candidate is up funnels through here. It stops the candidate and
# exits non-zero. It deliberately contains no prune, no worktree removal, and no command
# that touches the live service — the release under test is simply discarded.
fail_candidate() {
    local reason="$1"
    printf 'FAIL: %s\n' "${reason}" >&2
    stop_candidate
    dump_candidate_unit
    printf '\nThe candidate was stopped and discarded. Nothing was cut over:\n' >&2
    report_live_state >&2
    printf '   the release worktree is left in place for inspection; no worktree was pruned\n' >&2
    exit 1
}

wait_for_candidate() {
    local url="$1" deadline=$((SECONDS + CANDIDATE_TIMEOUT_SECS)) code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        code="$(http_code "${url}")"
        if [ "${code#2}" != "${code}" ] && [ "${#code}" -eq 3 ]; then
            echo "${code}"
            return 0
        fi
        sleep 3
    done
    echo "${code}"
    return 1
}

# Run the #833 harness against the candidate. Its assertions are not reimplemented here:
# it discovers every referenced stylesheet and script and rejects a 2xx that carries an
# empty or HTML body, which is the failure a status probe cannot see.
verify_candidate() {
    local base_url="$1"
    local args=(--base-url "${base_url}") routes=() checks=() route spec
    read -r -a routes <<<"${DEMO_CANDIDATE_ROUTES}"
    for route in ${routes[@]+"${routes[@]}"}; do
        args+=(--route "${route}")
    done
    if [ -n "${DEMO_CANDIDATE_API_BASE_URL}" ]; then
        args+=(--api-base-url "${DEMO_CANDIDATE_API_BASE_URL}")
    fi
    read -r -a checks <<<"${DEMO_CANDIDATE_API_CHECKS}"
    for spec in ${checks[@]+"${checks[@]}"}; do
        args+=(--api-check "${spec}")
    done
    [ -x "${VERIFY_HARNESS}" ] || die "verification harness missing: ${VERIFY_HARNESS}"
    "${VERIFY_HARNESS}" "${args[@]}"
}

# ---------------------------------------------------------------------------------------
# The migration gate (#834) — runs before any candidate starts
# ---------------------------------------------------------------------------------------

# Thin passthrough so callers and tests exercise the real gate. Exit 0 accepted, 3 refused.
run_migration_gate() {
    [ -f "${MIGRATION_GATE}" ] || die "migration gate missing: ${MIGRATION_GATE}"
    python3 "${MIGRATION_GATE}" "$@"
}

# The commit the live Demo release was cut from. That is the "previous code" the gate asks
# about compatibility with, so it is the correct baseline for pending-migration discovery.
live_release_commit() {
    local live
    live="$(readlink -f "${DEMO_CURRENT}" 2>/dev/null || true)"
    [ -n "${live}" ] || return 1
    [ -d "${live}" ] || return 1
    git -C "${live}" rev-parse HEAD 2>/dev/null || return 1
}

# Emit the gate's argv, one token per line. Pending == the migration files this release
# adds or changes relative to the live release. That is a pure git question: no database
# connection and no alembic import is needed at the front of a release.
#
# A diff that *errors* is not the same as a diff that finds nothing. A shallow clone, or a
# baseline commit this checkout does not have, would otherwise be silently reported as "no
# pending schema change" and the gate would accept without inspecting anything. That is a
# vacuous pass, so it is a hard failure instead.
migration_gate_args() {
    local release_dir="$1" base_sha="$2" target_sha="$3"
    local changed="" rel
    if [ -n "${base_sha}" ]; then
        if ! changed="$(git -C "${CANONICAL_ROOT}" diff --name-only --diff-filter=AMR \
            "${base_sha}" "${target_sha}" -- "${MIGRATIONS_VERSIONS_REL}" 2>/dev/null)"; then
            echo "FAIL: cannot diff ${base_sha} against ${target_sha} for pending migrations." >&2
            echo "      Refusing to read that as 'no pending schema change' — the additive-only" >&2
            echo "      gate would then accept without inspecting anything. Deepen the checkout" >&2
            echo "      (git fetch --unshallow) or set DEMO_MIGRATION_GATE_BASE_SHA to a commit" >&2
            echo "      this clone actually has." >&2
            return 1
        fi
    fi
    if [ -z "${changed}" ]; then
        # Still invoke the gate for real, with an empty pending set, so a release with no
        # schema change produces a genuine ACCEPTED verdict rather than a skipped step.
        printf '%s\n' "--migrations-dir" "${release_dir}/${MIGRATIONS_VERSIONS_REL}" "--revisions" ""
        return 0
    fi
    while IFS= read -r rel; do
        [ -n "${rel}" ] || continue
        printf '%s\n%s\n' "--migration-file" "${release_dir}/${rel}"
    done <<<"${changed}"
}

# ---------------------------------------------------------------------------------------
# The CI artifact (#837, ADR-058)
# ---------------------------------------------------------------------------------------

# Print the path of the tarball for ${sha} on stdout; everything chatty goes to stderr so
# the caller can capture the path. Fails loudly rather than falling back to a server-side
# build — compilation left the server on purpose.
fetch_release_artifact() {
    local sha="$1" short7="$2" dest_dir="$3"
    local name="juli-demo-${short7}" run_id="" tarball=""

    if [ -n "${DEMO_ARTIFACT_TARBALL:-}" ]; then
        echo "Using the operator-supplied artifact ${DEMO_ARTIFACT_TARBALL}" >&2
        printf '%s\n' "${DEMO_ARTIFACT_TARBALL}"
        return 0
    fi

    if ! command -v gh >/dev/null 2>&1; then
        echo "FAIL: gh is not installed, so the CI artifact ${name} cannot be downloaded." >&2
        echo "      Download it on a machine that has gh and re-run with" >&2
        echo "      DEMO_ARTIFACT_TARBALL=/path/to/${name}.tar.gz" >&2
        return 1
    fi

    mkdir -p "${dest_dir}"
    echo "Locating the release.yml run for ${sha}" >&2
    run_id="$(gh run list --commit "${sha}" --workflow release.yml --limit 20 \
        --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
    if [ -z "${run_id}" ]; then
        run_id="$(gh run list --commit "${sha}" --limit 50 \
            --json databaseId --jq '.[0].databaseId' 2>/dev/null || true)"
    fi
    if [ -z "${run_id}" ]; then
        echo "FAIL: no workflow run found for ${sha}; CI has not published ${name}." >&2
        echo "      Push the commit and let release.yml finish, or supply the tarball via" >&2
        echo "      DEMO_ARTIFACT_TARBALL=/path/to/${name}.tar.gz" >&2
        return 1
    fi
    echo "Downloading artifact ${name} from run ${run_id}" >&2
    if ! gh run download "${run_id}" --name "${name}" --dir "${dest_dir}" >&2; then
        echo "FAIL: artifact ${name} is not attached to run ${run_id}." >&2
        echo "      The app-release-artifact job did not publish a Demo artifact for this" >&2
        echo "      commit. Deploy a commit whose release.yml run is green, or supply the" >&2
        echo "      tarball via DEMO_ARTIFACT_TARBALL." >&2
        return 1
    fi
    tarball="$(find "${dest_dir}" -maxdepth 2 -name '*.tar.gz' -type f 2>/dev/null | head -n 1)"
    if [ -z "${tarball}" ]; then
        echo "FAIL: downloaded ${name} but found no tarball under ${dest_dir}." >&2
        return 1
    fi
    printf '%s\n' "${tarball}"
}

# Overlay the artifact onto the release worktree's apps/demo. The tarball is extracted
# rather than copied from a directory so the pnpm symlink farm survives (ADR-058); nothing
# below dereferences it. Refuses before writing anything if the artifact records a
# different commit, so a release directory is never half-populated by the wrong build.
place_release_artifact() {
    local tarball="$1" release_dir="$2" expected_sha="$3"
    local stage_root stage recorded dest entry name

    if [ ! -f "${tarball}" ]; then
        echo "FAIL: release artifact tarball not found: ${tarball}" >&2
        echo "      Nothing is compiled on the server (#837): the artifact must come from CI." >&2
        return 1
    fi
    stage_root="$(mktemp -d)" || return 1
    if ! tar -xzf "${tarball}" -C "${stage_root}"; then
        echo "FAIL: could not extract ${tarball}" >&2
        rm -rf "${stage_root}"
        return 1
    fi
    stage="$(find "${stage_root}" -maxdepth 1 -mindepth 1 -type d | head -n 1)"
    if [ -z "${stage}" ] || [ ! -d "${stage}" ]; then
        echo "FAIL: ${tarball} contained no artifact directory" >&2
        rm -rf "${stage_root}"
        return 1
    fi
    if [ ! -f "${stage}/release-artifact.json" ]; then
        echo "FAIL: ${tarball} carries no release-artifact.json — it is not an ADR-058 artifact" >&2
        rm -rf "${stage_root}"
        return 1
    fi
    recorded="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["commit"])' \
        "${stage}/release-artifact.json" 2>/dev/null || true)"
    if [ "${recorded}" != "${expected_sha}" ]; then
        echo "FAIL: artifact records commit ${recorded}, not the commit being deployed ${expected_sha}" >&2
        echo "      Refusing to place it; the release directory is left untouched." >&2
        rm -rf "${stage_root}"
        return 1
    fi

    dest="${release_dir}/apps/demo"
    mkdir -p "${dest}"
    for entry in "${stage}"/* "${stage}"/.[!.]*; do
        [ -e "${entry}" ] || continue
        name="$(basename "${entry}")"
        rm -rf "${dest:?}/${name}"
        cp -a "${entry}" "${dest}/${name}"
    done
    rm -rf "${stage_root}"
    echo "Placed ${tarball} (commit ${recorded}) into ${dest}"
}

# ---------------------------------------------------------------------------------------
# Deploy
# ---------------------------------------------------------------------------------------

main() {
    local sha short_sha short7 release_dir base_sha artifact_dir tarball
    local gate_args=() token candidate_url code live_before gate_argv_file
    local live_port candidate_port

    sha="${1:-}"
    if [ -z "${sha}" ]; then
        sha="$(git -C "${CANONICAL_ROOT}" rev-parse origin/main)"
    fi
    # The full 40-char commit: CI names the artifact from exactly the first 7 characters,
    # which `git rev-parse --short` does not promise.
    sha="$(git -C "${CANONICAL_ROOT}" rev-parse "${sha}")"
    short_sha="$(git -C "${CANONICAL_ROOT}" rev-parse --short "${sha}")"
    short7="${sha:0:7}"
    release_dir="${RELEASES_ROOT}/${short_sha}"

    # The live upstream definition — not this script's defaults — decides what is serving,
    # and therefore where the candidate may go. Read it before anything else happens.
    if ! live_port="$(live_upstream_port)"; then
        echo "FAIL: could not read the live upstream definition; nothing was cut over." >&2
        exit 1
    fi
    if ! candidate_port="$(demo_peer_port "${live_port}")"; then
        echo "FAIL: could not choose a candidate port; nothing was cut over." >&2
        exit 1
    fi
    LIVE_PORT="${live_port}"
    DEMO_CANDIDATE_PORT="${candidate_port}"
    CANDIDATE_UNIT="${DEMO_CANDIDATE_UNIT}-${candidate_port}"
    candidate_url="http://127.0.0.1:${candidate_port}"

    log "Juli Demo deploy — candidate-first (#838), graceful switch (#839): ${sha} (${short_sha})"
    live_before="$(readlink -f "${DEMO_CURRENT}" 2>/dev/null || echo NONE)"
    note "live now      : ${live_before} on 127.0.0.1:${live_port} (per ${DEMO_UPSTREAM_CONF})"
    note "candidate     : ${candidate_url} (loopback only; not reachable off this server)"
    mkdir -p "${RELEASES_ROOT}"

    # --- 1. Cut (or reuse) the release worktree. Additive only; never prunes. ---
    log "release worktree"
    if [ -d "${release_dir}" ]; then
        note "reusing ${release_dir} — re-checking out ${short_sha}"
        git -C "${release_dir}" fetch --depth 1 origin "${sha}"
        git -C "${release_dir}" checkout --force "${sha}"
    else
        note "creating ${release_dir}"
        git -C "${CANONICAL_ROOT}" fetch origin main
        git -C "${CANONICAL_ROOT}" worktree add --force "${release_dir}" "${sha}"
    fi

    # --- 2. Migration gate (#834) — BEFORE any candidate exists. ---
    log "migration gate (#834)"
    base_sha="${DEMO_MIGRATION_GATE_BASE_SHA:-}"
    if [ -z "${base_sha}" ]; then
        base_sha="$(live_release_commit || true)"
    fi
    if [ -n "${base_sha}" ]; then
        note "pending schema change measured against the live release ${base_sha:0:7}"
    else
        note "no previous live release resolvable — there is no earlier code to stay compatible with"
    fi
    # Written to a file rather than consumed through a process substitution so the
    # argv-building failure above is observable, and so the empty final line that carries
    # the empty --revisions value is not stripped the way command substitution would.
    gate_argv_file="$(mktemp)"
    if ! migration_gate_args "${release_dir}" "${base_sha}" "${sha}" >"${gate_argv_file}"; then
        rm -f "${gate_argv_file}"
        echo "FAIL: could not determine this release's pending migration set." >&2
        echo "      No candidate was started and nothing was cut over." >&2
        report_live_state >&2
        exit 1
    fi
    while IFS= read -r token; do
        gate_args+=("${token}")
    done <"${gate_argv_file}"
    rm -f "${gate_argv_file}"
    if ! run_migration_gate "${gate_args[@]}"; then
        echo "FAIL: the additive-only migration gate refused this release." >&2
        echo "      No candidate was started and nothing was cut over." >&2
        report_live_state >&2
        exit 1
    fi

    # --- 3. Fetch and place the CI artifact (closes the #837 deploy freeze). ---
    log "release artifact (#837, ADR-058)"
    [ -n "${short7}" ] || die "could not resolve a short commit for ${sha}"
    artifact_dir="${ARTIFACT_CACHE_ROOT}/${short7}"
    rm -rf "${artifact_dir:?}"
    if ! tarball="$(fetch_release_artifact "${sha}" "${short7}" "${artifact_dir}")"; then
        die "could not obtain the Demo release artifact for ${sha} — nothing was cut over."
    fi
    if ! place_release_artifact "${tarball}" "${release_dir}" "${sha}"; then
        die "could not place the Demo release artifact for ${sha} — nothing was cut over."
    fi

    # --- 4. The artifact must be complete before it is worth starting. ---
    log "artifact completeness (verify only; nothing is compiled here)"
    REPO_ROOT="${release_dir}" "${CANONICAL_ROOT}/infra/scripts/build-demo.sh"

    # --- 5. Start the CANDIDATE on a loopback port. The live instance is untouched. ---
    #
    # The candidate port is the peer of the live one, so anything still bound there is the
    # instance the PREVIOUS release promoted and then left running as its undo. It has long
    # since drained and it serves no public traffic, so freeing it now is safe — and it is
    # the only moment at which a previous instance is ever stopped.
    log "candidate on ${candidate_url}"
    free_candidate_port "${candidate_port}"
    if ! start_candidate "${release_dir}" "${DEMO_CANDIDATE_PORT}"; then
        fail_candidate "the candidate process would not start at all"
    fi
    if ! code="$(wait_for_candidate "${candidate_url}/decisions")"; then
        fail_candidate "the candidate never became ready within ${CANDIDATE_TIMEOUT_SECS}s (last HTTP ${code})"
    fi
    note "candidate answered HTTP ${code} on ${candidate_url}/decisions"

    # --- 6. Verify the candidate (#833) BEFORE any traffic moves. ---
    log "verification harness (#833) against the candidate"
    if ! verify_candidate "${candidate_url}"; then
        fail_candidate "the candidate failed release verification — it will not be cut over"
    fi

    # --- 7. Verified. THE GRACEFUL SWITCH (#839) — the first publicly visible step. ---
    #
    # The candidate is already up and has already passed verification, so nothing is
    # started, stopped, or restarted here: the upstream is repointed at a process that is
    # answering, and nginx is reloaded gracefully. No request can observe an unavailable
    # upstream, because at no instant is the upstream pointed at anything that is not
    # already serving.
    #
    # The switch goes first so that a rejected configuration leaves EVERYTHING as it was —
    # demo-current included. The candidate is deliberately not stopped: it is now live.
    log "verified — graceful cutover (#839)"
    if ! switch_demo_upstream "${candidate_port}"; then
        echo "FAIL: the upstream switch was refused, so nothing was cut over." >&2
        echo "      127.0.0.1:${live_port} is still serving and demo-current was not repointed." >&2
        report_live_state >&2
        echo "      The candidate is left running on :${candidate_port} for inspection; no" >&2
        echo "      release worktree was pruned or removed." >&2
        exit 1
    fi
    LIVE_PORT="${candidate_port}"
    note "demo.app-juli.com now resolves to 127.0.0.1:${candidate_port} (was ${live_port})"
    note "undo: ${DEMO_UPSTREAM_PREV} still names :${live_port}, which is still running"

    ln -sfn "${release_dir}" "${RELEASES_ROOT}/demo-current.tmp"
    mv -Tf "${RELEASES_ROOT}/demo-current.tmp" "${DEMO_CURRENT}"

    # Reboot durability. Transient candidate units do not survive a reboot; the durable
    # juli-demo.service does, and it must come back on the port nginx is pointed at.
    SYSTEMD_SRC="${CANONICAL_ROOT}/infra/systemd/juli-demo.service"
    if [ -f "${SYSTEMD_SRC}" ]; then
        install -m 0644 "${SYSTEMD_SRC}" /etc/systemd/system/juli-demo.service
        systemctl daemon-reload
    fi
    write_demo_runtime_env "${candidate_port}" ||
        die "cut over, but could not record the live port in ${DEMO_RUNTIME_ENV}."

    log "post-cutover health check (timeout ${HEALTH_TIMEOUT_SECS}s)"
    local deadline=$((SECONDS + HEALTH_TIMEOUT_SECS)) demo_ok=false demo_code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        demo_code="$(http_code "http://127.0.0.1:${LIVE_PORT}/decisions")"
        if [ "${#demo_code}" -eq 3 ] && [ "${demo_code#2}" != "${demo_code}" ]; then
            demo_ok=true
            break
        fi
        sleep 3
    done
    if [ "${demo_ok}" != true ]; then
        # The candidate passed and this still failed, so the fault is in cutover, not in
        # the release. Automatic post-cutover rollback is #840; say so rather than guess.
        echo "FAIL: Demo is not healthy on :${LIVE_PORT} after cutover (last_code=${demo_code})." >&2
        echo "      The release itself passed candidate verification, so this is a cutover" >&2
        echo "      fault. The previous instance on :${live_port} is still running, so the" >&2
        echo "      fastest undo is to restore the retained definition and reload:" >&2
        echo "        cp -p ${DEMO_UPSTREAM_PREV} ${DEMO_UPSTREAM_CONF} && nginx -t && systemctl reload nginx" >&2
        echo "      That returns traffic to ${live_before}. Automating it is #840." >&2
        systemctl --no-pager --full status "${CANDIDATE_UNIT}" >&2 || true
        journalctl -u "${CANDIDATE_UNIT}" -n 80 --no-pager >&2 || true
        exit 1
    fi
    echo "PASS: Demo is healthy on the verified release (:${LIVE_PORT}/decisions returned 2xx)."

    # --- 8. Record, then prune. Pruning happens only after a successful cutover. ---
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha}" "${release_dir}" >> "${HISTORY_LOG}"
    log "pruning old release worktrees (keeping last ${KEEP_DEMO_RELEASES} per lane)"
    prune_release_worktrees "${CANONICAL_ROOT}" "${RELEASES_ROOT}" "${KEEP_DEMO_RELEASES}" "${release_dir}"

    log "Demo deploy complete: ${sha} live via ${DEMO_CURRENT} -> ${release_dir}"
}

# Library mode: define the functions and deploy nothing. Used by
# tests/unit/test_demo_candidate_verification.py to exercise them for real.
if [ "${DEMO_DEPLOY_SOURCE_ONLY:-0}" != "1" ]; then
    main "$@"
fi
