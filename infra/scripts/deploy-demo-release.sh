#!/usr/bin/env bash
# Continuous delivery for Demo only: cut a release worktree, verify the Demo
# artifact CI built for this commit, cut over the demo-current symlink, restart
# juli-demo, and health-check. No compilation happens on the server (#837).
#
# Independent of deploy-release.sh — juli-api and juli-web are not restarted.
# Run from the canonical checkout on the VPS (~/Juli-AI-v2).
#
# Release model:
#   ~/Juli-AI-v2              canonical clone; source of truth for `git worktree add`
#   ~/releases/<short-sha>/   one worktree per release (shared with App Review deploys)
#   ~/releases/demo-current   symlink to the active Demo release
#   ~/releases/demo-deploy-history.log   append-only log for Demo rollback
#
# Local health probe: http://127.0.0.1:3001/decisions must return 2xx before success.
#
# Usage (on the VPS):
#   cd ~/Juli-AI-v2 && git fetch origin main && git checkout main && git pull
#   ./infra/scripts/deploy-demo-release.sh <sha>
#   ./infra/scripts/deploy-demo-release.sh                 # defaults to origin/main HEAD
#
# Env overrides: KEEP_DEMO_RELEASES (default 3), HEALTH_TIMEOUT_SECS (default 60).
set -euo pipefail

CANONICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
DEMO_CURRENT="${RELEASES_ROOT}/demo-current"
HISTORY_LOG="${RELEASES_ROOT}/demo-deploy-history.log"
KEEP_DEMO_RELEASES="${KEEP_DEMO_RELEASES:-3}"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
DEMO_PORT="3001"

# shellcheck source=infra/scripts/lib/prune-releases.sh
source "${CANONICAL_ROOT}/infra/scripts/lib/prune-releases.sh"

sha="${1:-}"
if [ -z "${sha}" ]; then
    sha="$(git -C "${CANONICAL_ROOT}" rev-parse origin/main)"
fi
short_sha="$(git -C "${CANONICAL_ROOT}" rev-parse --short "${sha}")"
release_dir="${RELEASES_ROOT}/${short_sha}"

echo "== Juli Demo deploy: ${sha} (${short_sha}) =="
mkdir -p "${RELEASES_ROOT}"

# --- 1. Cut (or reuse) the release worktree ---
if [ -d "${release_dir}" ]; then
    echo "Release dir ${release_dir} already exists — re-checking out ${short_sha}."
    git -C "${release_dir}" fetch --depth 1 origin "${sha}"
    git -C "${release_dir}" checkout --force "${sha}"
else
    echo "Creating release worktree at ${release_dir}."
    git -C "${CANONICAL_ROOT}" fetch origin main
    git -C "${CANONICAL_ROOT}" worktree add --force "${release_dir}" "${sha}"
fi

# --- 2. Verify the release directory carries a runnable Demo artifact ---
# Nothing is compiled here any more (#837, ADR-058): CI builds the artifact and
# packages it with a production dependency tree resolved there. This step only
# checks that the artifact is present and complete before cutover. Placing it into
# the release directory is #838.
echo "-- demo frontend (verify only) --"
REPO_ROOT="${release_dir}" "${CANONICAL_ROOT}/infra/scripts/build-demo.sh"

NEXT_BIN="${release_dir}/apps/demo/node_modules/.bin/next"
if [ ! -e "${NEXT_BIN}" ]; then
    echo "FAIL: next binary missing from the placed artifact: ${NEXT_BIN}" >&2
    exit 1
fi

# --- 3. Install/refresh systemd unit (keeps ExecStart in sync with repo) ---
SYSTEMD_SRC="${CANONICAL_ROOT}/infra/systemd/juli-demo.service"
if [ -f "${SYSTEMD_SRC}" ]; then
    echo "-- install juli-demo.service --"
    install -m 0644 "${SYSTEMD_SRC}" /etc/systemd/system/juli-demo.service
    systemctl daemon-reload
fi

# --- 4. Cut over: atomically flip the demo-current symlink ---
echo "-- cutover --"
ln -sfn "${release_dir}" "${RELEASES_ROOT}/demo-current.tmp"
mv -Tf "${RELEASES_ROOT}/demo-current.tmp" "${DEMO_CURRENT}"

# --- 5. Restart Demo service only ---
systemctl restart juli-demo

# --- 6. Local health check before success ---
echo "-- health check (timeout ${HEALTH_TIMEOUT_SECS}s) --"
deadline=$((SECONDS + HEALTH_TIMEOUT_SECS))
demo_ok=false
demo_code="000"
while [ "${SECONDS}" -lt "${deadline}" ]; do
    demo_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${DEMO_PORT}/decisions" || true)"
    [[ "${demo_code}" =~ ^2 ]] && demo_ok=true
    if [ "${demo_ok}" = true ]; then
        break
    fi
    sleep 3
done

if [ "${demo_ok}" != true ]; then
    echo "FAIL: Demo health check did not pass within ${HEALTH_TIMEOUT_SECS}s (last_code=${demo_code})." >&2
    echo "The new Demo release is live at ${DEMO_CURRENT} — run rollback-demo-release.sh if this is a regression." >&2
    echo "-- juli-demo status --" >&2
    systemctl --no-pager --full status juli-demo || true
    echo "-- juli-demo recent logs --" >&2
    journalctl -u juli-demo -n 80 --no-pager || true
    exit 1
fi
echo "PASS: juli-demo is healthy on the new release (/decisions returned 2xx)."

# --- 7. Record + prune history ---
printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha}" "${release_dir}" >> "${HISTORY_LOG}"

# Shared with deploy-release.sh so neither lane can delete a worktree the other
# is live on — see infra/scripts/lib/prune-releases.sh.
echo "-- pruning old release worktrees (keeping last ${KEEP_DEMO_RELEASES} per lane) --"
prune_release_worktrees "${CANONICAL_ROOT}" "${RELEASES_ROOT}" "${KEEP_DEMO_RELEASES}" "${release_dir}"

echo "== Demo deploy complete: ${sha} live via ${DEMO_CURRENT} -> ${release_dir} =="
