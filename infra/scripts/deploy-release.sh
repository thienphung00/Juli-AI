#!/usr/bin/env bash
# Continuous delivery: cut a new release worktree, run migrations, build both
# services, cut over, restart, and health-check. Run from the canonical
# checkout on the VPS (~/Juli-AI-v2) after `git pull`, via release.yml.
#
# Release model (no Docker/containers — plain git worktrees):
#   ~/Juli-AI-v2            canonical clone; source of truth for `git worktree add`
#   ~/releases/<short-sha>/ one worktree per release (own .venv + web/node_modules)
#   ~/releases/current      symlink to the active release — systemd units point here
#   ~/releases/deploy-history.log   append-only log consumed by rollback-release.sh
#
# Env/secrets are NOT per-release: fetch-secrets.sh (run first, below) writes
# /etc/juli/api.env and /etc/juli/web.env, which survive across
# releases and rollbacks.
#
# Usage (on the VPS, from the canonical checkout):
#   cd ~/Juli-AI-v2 && git fetch origin main && git checkout main && git pull
#   ./infra/scripts/deploy-release.sh <sha>
#   ./infra/scripts/deploy-release.sh                 # defaults to origin/main HEAD
#
# Env overrides: KEEP_RELEASES (default 3), HEALTH_TIMEOUT_SECS (default 60).
set -euo pipefail

CANONICAL_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
HISTORY_LOG="${RELEASES_ROOT}/deploy-history.log"
KEEP_RELEASES="${KEEP_RELEASES:-3}"
HEALTH_TIMEOUT_SECS="${HEALTH_TIMEOUT_SECS:-60}"
API_ENV_FILE="/etc/juli/api.env"
WEB_ENV_FILE="/etc/juli/web.env"

sha="${1:-}"
if [ -z "${sha}" ]; then
    sha="$(git -C "${CANONICAL_ROOT}" rev-parse origin/main)"
fi
short_sha="$(git -C "${CANONICAL_ROOT}" rev-parse --short "${sha}")"
release_dir="${RELEASES_ROOT}/${short_sha}"

echo "== Juli deploy: ${sha} (${short_sha}) =="
mkdir -p "${RELEASES_ROOT}"

# --- 1. Refresh secrets before building so the new release's env is current ---
if [ -x "${CANONICAL_ROOT}/infra/scripts/fetch-secrets.sh" ]; then
    "${CANONICAL_ROOT}/infra/scripts/fetch-secrets.sh"
else
    echo "WARN: fetch-secrets.sh missing or not executable — reusing existing ${API_ENV_FILE}/${WEB_ENV_FILE}" >&2
fi

for f in "${API_ENV_FILE}" "${WEB_ENV_FILE}"; do
    if [ ! -f "${f}" ]; then
        echo "FAIL: ${f} does not exist. Run fetch-secrets.sh (or seed it manually) before first deploy." >&2
        exit 1
    fi
done

# --- 2. Cut (or reuse) the release worktree ---
if [ -d "${release_dir}" ]; then
    echo "Release dir ${release_dir} already exists — re-checking out ${short_sha}."
    git -C "${release_dir}" fetch --depth 1 origin "${sha}"
    git -C "${release_dir}" checkout --force "${sha}"
else
    echo "Creating release worktree at ${release_dir}."
    git -C "${CANONICAL_ROOT}" fetch origin main
    git -C "${CANONICAL_ROOT}" worktree add --force "${release_dir}" "${sha}"
fi

# --- 3. Backend: venv + deps + migrations ---
echo "-- backend --"
if [ ! -d "${release_dir}/.venv" ]; then
    python3 -m venv "${release_dir}/.venv"
fi
"${release_dir}/.venv/bin/pip" install -q -r "${release_dir}/requirements.txt"
"${release_dir}/.venv/bin/pip" install -q -e "${release_dir}/backend"

set -a
# shellcheck disable=SC1090
source "${API_ENV_FILE}"
set +a
( cd "${release_dir}" && "${release_dir}/.venv/bin/alembic" upgrade head )

# --- 4. Frontend: build with the App Review env baked in ---
echo "-- frontend --"
cp "${WEB_ENV_FILE}" "${release_dir}/web/.env.production"
"${release_dir}/infra/scripts/build-frontend-review.sh"

# --- 5. Cut over: atomically flip the `current` symlink ---
echo "-- cutover --"
ln -sfn "${release_dir}" "${RELEASES_ROOT}/current.tmp"
mv -Tf "${RELEASES_ROOT}/current.tmp" "${RELEASES_ROOT}/current"

# --- 6. Restart both services on the new release ---
systemctl restart juli-api
systemctl restart juli-web

# --- 7. Health check — fail loudly, no auto-rollback (manual rollback.yml) ---
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
    echo "FAIL: health check did not pass within ${HEALTH_TIMEOUT_SECS}s (api_ok=${api_ok} web_ok=${web_ok})." >&2
    echo "The new release is live at ~/releases/current — run rollback.yml if this is a regression." >&2
    exit 1
fi
echo "PASS: juli-api and juli-web are healthy on the new release."

# --- 8. Record + prune history ---
mkdir -p "${RELEASES_ROOT}"
printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha}" "${release_dir}" >> "${HISTORY_LOG}"

echo "-- pruning old releases (keeping last ${KEEP_RELEASES}) --"
mapfile -t old_releases < <(git -C "${CANONICAL_ROOT}" worktree list --porcelain \
    | awk '/^worktree /{print $2}' \
    | grep -F "${RELEASES_ROOT}/" \
    | sort -r \
    | tail -n "+$((KEEP_RELEASES + 1))")
for old in "${old_releases[@]:-}"; do
    [ -n "${old}" ] || continue
    [ "${old}" = "${release_dir}" ] && continue
    echo "Removing old release worktree: ${old}"
    git -C "${CANONICAL_ROOT}" worktree remove --force "${old}" || rm -rf "${old}"
done

echo "== Deploy complete: ${sha} live via ~/releases/current -> ${release_dir} =="
