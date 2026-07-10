#!/usr/bin/env bash
# Manual rollback: re-point ~/releases/current at a previous release worktree
# and restart both services. No blue/green, no automated rollback-on-failure —
# this is the "symlink back + restart" mechanism called for in the CD prompt.
#
# Usage (on the VPS, or via rollback.yml over SSH):
#   ./infra/scripts/rollback-release.sh                # roll back to the previous release
#   ./infra/scripts/rollback-release.sh <sha-or-short-sha>   # roll back to a specific release
set -euo pipefail

RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
HISTORY_LOG="${RELEASES_ROOT}/deploy-history.log"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"

target="${1:-}"

if [ ! -f "${HISTORY_LOG}" ]; then
    echo "FAIL: no ${HISTORY_LOG} found — nothing to roll back to." >&2
    exit 1
fi

current_target="$(readlink -f "${RELEASES_ROOT}/current" || true)"

if [ -n "${target}" ]; then
    release_dir="$(grep " ${target}" "${HISTORY_LOG}" | tail -1 | awk '{print $3}')"
    if [ -z "${release_dir}" ]; then
        # Allow passing the release dir's short-sha directly.
        release_dir="${RELEASES_ROOT}/${target}"
    fi
else
    # Previous entry that isn't the currently-live release dir.
    release_dir="$(tac "${HISTORY_LOG}" | awk -v cur="${current_target}" '$3 != cur {print $3; exit}')"
fi

if [ -z "${release_dir}" ] || [ ! -d "${release_dir}" ]; then
    echo "FAIL: could not resolve a rollback target release dir (target='${target}')." >&2
    echo "Available releases:" >&2
    awk '{print "  " $2, $3}' "${HISTORY_LOG}" >&2
    exit 1
fi

if [ "${release_dir}" = "${current_target}" ]; then
    echo "WARN: resolved rollback target is the currently live release (${release_dir}) — nothing to do." >&2
    exit 0
fi

echo "== Rolling back: ${current_target:-<unknown>} -> ${release_dir} =="

ln -sfn "${release_dir}" "${RELEASES_ROOT}/current.tmp"
mv -Tf "${RELEASES_ROOT}/current.tmp" "${RELEASES_ROOT}/current"

systemctl restart juli-api
systemctl restart juli-web

echo "-- health check (timeout ${HEALTH_TIMEOUT_SECS}s) --"
deadline=$((SECONDS + HEALTH_TIMEOUT_SECS))
api_ok=false
web_ok=false
while [ "${SECONDS}" -lt "${deadline}" ]; do
    api_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/health || true)"
    web_code="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:3000/ || true)"
    [[ "${api_code}" =~ ^2 ]] && api_ok=true
    [[ "${web_code}" =~ ^2 ]] && web_ok=true
    if [ "${api_ok}" = true ] && [ "${web_ok}" = true ]; then
        break
    fi
    sleep 3
done

if [ "${api_ok}" != true ] || [ "${web_ok}" != true ]; then
    echo "FAIL: post-rollback health check did not pass within ${HEALTH_TIMEOUT_SECS}s (api_ok=${api_ok} web_ok=${web_ok})." >&2
    exit 1
fi

printf '%s ROLLBACK-TO %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${release_dir}" >> "${HISTORY_LOG}"
echo "PASS: rolled back to ${release_dir}; juli-api and juli-web are healthy."
