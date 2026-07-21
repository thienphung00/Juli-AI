#!/usr/bin/env bash
# Manual Demo rollback: re-point ~/releases/demo-current at a previous release
# worktree and restart juli-demo only. Does not affect App Review services.
#
# Local health probe: http://127.0.0.1:3001/decisions must return 2xx before success.
#
# Usage (on the VPS):
#   ./infra/scripts/rollback-demo-release.sh                # roll back to the previous Demo release
#   ./infra/scripts/rollback-demo-release.sh <sha-or-short-sha>
set -euo pipefail

RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
DEMO_CURRENT="${RELEASES_ROOT}/demo-current"
HISTORY_LOG="${RELEASES_ROOT}/demo-deploy-history.log"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
DEMO_PORT="3001"

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

echo "== Rolling back Demo: ${current_target:-<unknown>} -> ${release_dir} =="

ln -sfn "${release_dir}" "${RELEASES_ROOT}/demo-current.tmp"
mv -Tf "${RELEASES_ROOT}/demo-current.tmp" "${DEMO_CURRENT}"

systemctl restart juli-demo

echo "-- health check (timeout ${HEALTH_TIMEOUT_SECS}s) --"
deadline=$((SECONDS + HEALTH_TIMEOUT_SECS))
demo_ok=false
while [ "${SECONDS}" -lt "${deadline}" ]; do
    demo_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${DEMO_PORT}/decisions" || true)"
    [[ "${demo_code}" =~ ^2 ]] && demo_ok=true
    if [ "${demo_ok}" = true ]; then
        break
    fi
    sleep 3
done

if [ "${demo_ok}" != true ]; then
    echo "FAIL: post-rollback Demo health check did not pass within ${HEALTH_TIMEOUT_SECS}s (demo_ok=${demo_ok})." >&2
    exit 1
fi

printf '%s ROLLBACK-TO %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${release_dir}" >> "${HISTORY_LOG}"
echo "PASS: rolled back Demo to ${release_dir}; juli-demo is healthy on /decisions."
