#!/usr/bin/env bash
# Landing page deploy — its first production home (#841).
#
# Deliberately the SIMPLE lane: one fixed port, restart-based cutover, verify after
# start. Candidate verification, the graceful switch, and automatic rollback come to
# Landing with the paired-slot extension (#843); the single deploy command replaces
# this script entirely in #844. Keeping this thin is the point — it must be easy to
# retire.
#
# What it guarantees today:
#   * nothing is compiled on the server (#837): the CI artifact juli-landing-<short7>
#     is fetched and placed, exactly like the Demo lane
#   * assets are verified per #833 against the running instance before success
#   * the API, Demo, and App Review services are never touched (#841 AC): the only
#     unit this script knows is juli-landing
#   * the release pool discipline holds: one worktree per release under ~/releases,
#     landing-current symlink, append-only history, prune-after-success only
#
# PORT MAP (host-wide, every port unique):
#   8000  juli-api        3000  juli-web        3001/3021  Demo blue-green lane
#   3007  juli-landing    3027  RESERVED for the Landing candidate peer (#843)
#   6379  redis
# 3007 is what apps/landing/package.json already encodes for `next start`; production
# adopts it so dev and prod agree on one number.
#
# Usage (on the VPS):
#   cd ~/Juli-AI-v2 && git pull
#   ./infra/scripts/deploy-landing-release.sh <sha>     # or no arg for origin/main HEAD
set -euo pipefail

CANONICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
LANDING_CURRENT="${RELEASES_ROOT}/landing-current"
HISTORY_LOG="${RELEASES_ROOT}/landing-deploy-history.log"
KEEP_LANDING_RELEASES="${KEEP_LANDING_RELEASES:-3}"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
LANDING_PORT="${LANDING_PORT:-3007}"
LANDING_UNIT="juli-landing"
LANDING_ROUTES="${LANDING_ROUTES:-/}"
ARTIFACT_CACHE_ROOT="${ARTIFACT_CACHE_ROOT:-$HOME/.cache/juli-release-artifacts}"
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

# Same ADR-058 contract as the Demo lane: tarball from CI, commit recorded inside it
# must match the commit being deployed, nothing compiled here.
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

verify_landing() {
    local base_url="$1" route args=(--base-url "$1") routes=()
    read -r -a routes <<<"${LANDING_ROUTES}"
    for route in ${routes[@]+"${routes[@]}"}; do
        args+=(--route "${route}")
    done
    [ -x "${VERIFY_HARNESS}" ] || die "verification harness missing: ${VERIFY_HARNESS}"
    "${VERIFY_HARNESS}" "${args[@]}"
}

main() {
    local sha="${1:-}" short_sha short7 release_dir artifact_dir tarball
    local deadline code ok

    if [ -z "${sha}" ]; then
        git -C "${CANONICAL_ROOT}" fetch origin main
        sha="$(git -C "${CANONICAL_ROOT}" rev-parse origin/main)"
    fi
    short_sha="$(git -C "${CANONICAL_ROOT}" rev-parse --short "${sha}")"
    short7="${sha:0:7}"
    release_dir="${RELEASES_ROOT}/${short_sha}"

    log "Juli Landing deploy (#841): ${sha} (${short_sha}) on 127.0.0.1:${LANDING_PORT}"
    mkdir -p "${RELEASES_ROOT}"

    # --- 1. Release worktree (shared pool discipline) ---
    if [ -d "${release_dir}" ]; then
        note "reusing ${release_dir} — re-checking out ${short_sha}"
        git -C "${release_dir}" fetch --depth 1 origin "${sha}"
        git -C "${release_dir}" checkout --force "${sha}"
    else
        note "creating release worktree at ${release_dir}"
        git -C "${CANONICAL_ROOT}" fetch origin main
        git -C "${CANONICAL_ROOT}" worktree add --force "${release_dir}" "${sha}"
    fi

    # --- 2. CI artifact (#837): fetch, verify provenance, place ---
    log "release artifact (#837, ADR-058)"
    artifact_dir="${ARTIFACT_CACHE_ROOT}/landing-${short7}"
    rm -rf "${artifact_dir:?}"
    tarball="$(fetch_landing_artifact "${sha}" "${short7}" "${artifact_dir}")" ||
        die "could not obtain the Landing release artifact for ${sha} — nothing changed."
    place_landing_artifact "${tarball}" "${release_dir}" "${sha}" ||
        die "could not place the Landing release artifact — nothing changed."

    # --- 3. Cut over the symlink, install the unit, restart. Landing has no paired ---
    # slots yet (#843), so this restart IS the error window; it is seconds long and
    # the page is not yet on the main domain (#842).
    log "cutover — landing-current -> ${release_dir}"
    ln -sfn "${release_dir}" "${RELEASES_ROOT}/landing-current.tmp"
    mv -Tf "${RELEASES_ROOT}/landing-current.tmp" "${LANDING_CURRENT}"
    install -m 0644 "${CANONICAL_ROOT}/infra/systemd/juli-landing.service" \
        /etc/systemd/system/juli-landing.service
    systemctl daemon-reload
    systemctl enable "${LANDING_UNIT}" >/dev/null 2>&1 || true
    systemctl restart "${LANDING_UNIT}"

    # --- 4. Health, then #833 asset verification against the running instance ---
    log "health check on 127.0.0.1:${LANDING_PORT} (timeout ${HEALTH_TIMEOUT_SECS}s)"
    deadline=$((SECONDS + HEALTH_TIMEOUT_SECS)); ok=false; code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        code="$(http_code "http://127.0.0.1:${LANDING_PORT}/")"
        if [ "${#code}" -eq 3 ] && [ "${code#2}" != "${code}" ]; then
            ok=true
            break
        fi
        sleep 3
    done
    if [ "${ok}" != true ]; then
        systemctl --no-pager --full status "${LANDING_UNIT}" >&2 || true
        journalctl -u "${LANDING_UNIT}" -n 60 --no-pager >&2 || true
        die "Landing is not healthy on :${LANDING_PORT} (last HTTP ${code})."
    fi
    log "verification harness (#833)"
    verify_landing "http://127.0.0.1:${LANDING_PORT}" ||
        die "Landing failed asset verification on :${LANDING_PORT}."

    # --- 5. Record, then prune (shared-pool safe: *current targets are protected) ---
    printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha}" "${release_dir}" >> "${HISTORY_LOG}"
    log "pruning old release worktrees (keeping last ${KEEP_LANDING_RELEASES} per lane)"
    prune_release_worktrees "${CANONICAL_ROOT}" "${RELEASES_ROOT}" "${KEEP_LANDING_RELEASES}" "${release_dir}"

    log "Landing deploy complete: ${sha} live on 127.0.0.1:${LANDING_PORT} via ${LANDING_CURRENT} -> ${release_dir}"
}

if [ "${LANDING_DEPLOY_SOURCE_ONLY:-0}" != "1" ]; then
    main "$@"
fi
