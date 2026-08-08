#!/usr/bin/env bash
# Manual Demo rollback: put a previous release back in front of visitors.
# Does not affect App Review services.
#
# GRACEFUL SINCE #839. This no longer restarts the live process. It starts the target
# release on the free member of the Demo port pair, waits for it to answer, and only then
# repoints the deployment-owned upstream definition and reloads nginx gracefully — the
# same switch a deploy uses. A rollback therefore drops no in-flight request either, and
# if the target never becomes healthy nothing is switched at all.
#
# THE FASTEST UNDO of the release that was just cut over needs neither this script nor a
# wait: the deploy retained the definition naming the previous instance, and that instance
# is still running.
#
#   cp -p /etc/nginx/juli/demo-upstream.conf.prev /etc/nginx/juli/demo-upstream.conf \
#     && nginx -t && systemctl reload nginx
#
# Use this script when that instance is gone (after a reboot) or to reach an older release.
# Automating the undo on a failed post-cutover check is #840.
#
# Usage (on the VPS):
#   ./infra/scripts/rollback-demo-release.sh                # previous Demo release
#   ./infra/scripts/rollback-demo-release.sh <sha-or-short-sha>
set -euo pipefail

CANONICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
DEMO_CURRENT="${RELEASES_ROOT}/demo-current"
HISTORY_LOG="${RELEASES_ROOT}/demo-deploy-history.log"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
CANDIDATE_TIMEOUT_SECS="${CANDIDATE_TIMEOUT_SECS:-${HEALTH_TIMEOUT_SECS}}"

# The switch mechanics live in exactly one place — and are exercised for real by
# tests/unit/test_demo_upstream_switch.py — so rollback and deploy are incapable of
# disagreeing about what is serving. DEMO_DEPLOY_SOURCE_ONLY=1 defines the functions and
# deploys nothing. Nothing below prunes or removes a release worktree: ~/releases is one
# pool shared by every deploy lane.
DEMO_DEPLOY_SOURCE_ONLY=1
export DEMO_DEPLOY_SOURCE_ONLY
# shellcheck source=infra/scripts/deploy-demo-release.sh
source "${CANONICAL_ROOT}/infra/scripts/deploy-demo-release.sh"

target="${1:-}"

if [ ! -f "${HISTORY_LOG}" ]; then
    echo "FAIL: no ${HISTORY_LOG} found — nothing to roll back to." >&2
    exit 1
fi

current_target="$(readlink -f "${DEMO_CURRENT}" || true)"

if [ -n "${target}" ]; then
    release_dir="$(grep " ${target}" "${HISTORY_LOG}" | tail -1 | awk '{print $3}')"
    if [ -z "${release_dir}" ]; then
        release_dir="${RELEASES_ROOT}/${target}"
    fi
else
    release_dir="$(tac "${HISTORY_LOG}" | awk -v cur="${current_target}" '$3 != cur {print $3; exit}')"
fi

if [ -z "${release_dir}" ] || [ ! -d "${release_dir}" ]; then
    echo "FAIL: could not resolve a Demo rollback target (target='${target}')." >&2
    echo "Available Demo releases:" >&2
    awk '{print "  " $2, $3}' "${HISTORY_LOG}" >&2
    exit 1
fi

if [ "${release_dir}" = "${current_target}" ]; then
    echo "WARN: resolved rollback target is the currently live Demo release (${release_dir}) — nothing to do." >&2
    exit 0
fi

# What is serving comes from the live upstream definition, never from a hard-coded port.
if ! live_port="$(live_upstream_port)"; then
    echo "FAIL: could not read what is serving; nothing was rolled back." >&2
    exit 1
fi
if ! rollback_port="$(demo_peer_port "${live_port}")"; then
    echo "FAIL: could not choose a port for the rollback instance." >&2
    exit 1
fi
LIVE_PORT="${live_port}"
CANDIDATE_UNIT="${DEMO_CANDIDATE_UNIT}-${rollback_port}"

echo "== Rolling back Demo: ${current_target:-<unknown>} -> ${release_dir} =="
echo "   live now      : 127.0.0.1:${live_port}"
echo "   rollback onto : 127.0.0.1:${rollback_port} (nothing public moves until it is healthy)"

free_candidate_port "${rollback_port}"
if ! start_candidate "${release_dir}" "${rollback_port}"; then
    echo "FAIL: could not start ${release_dir} on :${rollback_port}." >&2
    echo "      Nothing was switched; 127.0.0.1:${live_port} is still serving." >&2
    dump_candidate_unit
    exit 1
fi

echo "-- health check on the rollback instance (timeout ${CANDIDATE_TIMEOUT_SECS}s) --"
if ! demo_code="$(wait_for_candidate "http://127.0.0.1:${rollback_port}/decisions")"; then
    echo "FAIL: ${release_dir} never became healthy on :${rollback_port} (last HTTP ${demo_code})." >&2
    echo "      Nothing was switched; 127.0.0.1:${live_port} is still serving." >&2
    stop_candidate
    dump_candidate_unit
    exit 1
fi
echo "   rollback instance answered HTTP ${demo_code}"

# The switch first: if it is refused, demo-current is still where it was.
if ! switch_demo_upstream "${rollback_port}"; then
    echo "FAIL: the upstream switch was refused; 127.0.0.1:${live_port} is still serving" >&2
    echo "      and demo-current was not repointed." >&2
    exit 1
fi
LIVE_PORT="${rollback_port}"

ln -sfn "${release_dir}" "${RELEASES_ROOT}/demo-current.tmp"
mv -Tf "${RELEASES_ROOT}/demo-current.tmp" "${DEMO_CURRENT}"
write_demo_runtime_env "${rollback_port}" ||
    echo "WARN: rolled back, but could not record the live port in ${DEMO_RUNTIME_ENV}." >&2

printf '%s ROLLBACK-TO %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${release_dir}" >> "${HISTORY_LOG}"
echo "PASS: rolled back Demo to ${release_dir}, now serving on 127.0.0.1:${rollback_port}."
