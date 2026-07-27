#!/usr/bin/env bash
# Build the Demo frontend (apps/demo) with mock data only.
#
# No backend credentials or NEXT_PUBLIC_API_URL are required — the Demo is
# self-contained. Always run this before restarting juli-demo when code changes.
#
# On the VPS, juli-demo serves ~/releases/demo-current/apps/demo. Prefer
# ./infra/scripts/deploy-demo-release.sh so the build lands in the release
# worktree that the service actually runs.
#
# Usage (on the VPS or locally):
#   cd ~/Juli-AI-v2
#   ./infra/scripts/build-demo.sh
#   DEMO_RELEASE_BUILD=1 REPO_ROOT=~/releases/<sha> ./infra/scripts/build-demo.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DEMO_DIR="${REPO_ROOT}/apps/demo"
ENV_FILE="${DEMO_DIR}/.env.production"
ENV_EXAMPLE="${REPO_ROOT}/infra/scripts/env/demo.env.example"

if [ ! -d "${DEMO_DIR}" ]; then
    echo "Missing ${DEMO_DIR}" >&2
    exit 1
fi

if [ ! -f "${ENV_FILE}" ] && [ -f "${ENV_EXAMPLE}" ]; then
    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    echo "Created ${ENV_FILE} from template (mock mode — no secrets required)."
fi

_demo_service_app_dir() {
    local unit="/etc/systemd/system/juli-demo.service"
    [ -f "${unit}" ] || return 1
    grep -E '^WorkingDirectory=' "${unit}" | head -1 | cut -d= -f2-
}

_is_release_build() {
    [ "${DEMO_RELEASE_BUILD:-}" = "1" ] && return 0
    case "${REPO_ROOT}" in
        */releases/*) return 0 ;;
        *) return 1 ;;
    esac
}

echo "== Juli Demo frontend build (apps/demo, mock mode) =="

# Guard accidental builds in the canonical checkout while juli-demo serves
# demo-current. Release deploys build into ~/releases/<sha> before cutover, so
# a temporary path mismatch is expected — skip the guard for those builds.
if ! _is_release_build; then
    if service_app_dir="$(_demo_service_app_dir)"; then
        build_app_dir="$(cd "${DEMO_DIR}" && pwd)"
        service_resolved="$(readlink -f "${service_app_dir}" 2>/dev/null || echo "${service_app_dir}")"
        build_resolved="$(readlink -f "${build_app_dir}")"
        if [ "${service_resolved}" != "${build_resolved}" ]; then
            if [ "${DEMO_BUILD_ALLOW_MISMATCH:-}" != "1" ]; then
                echo "FAIL: juli-demo serves ${service_resolved} but this build writes to ${build_resolved}." >&2
                echo "On the VPS run: ./infra/scripts/deploy-demo-release.sh" >&2
                echo "Local dev only: DEMO_BUILD_ALLOW_MISMATCH=1 ./infra/scripts/build-demo.sh" >&2
                exit 1
            fi
            echo "WARN: build dir != juli-demo WorkingDirectory (DEMO_BUILD_ALLOW_MISMATCH=1)."
        fi
    fi
fi

cd "${REPO_ROOT}"
corepack enable pnpm 2>/dev/null || true
pnpm install --frozen-lockfile --filter @juli/demo...

# Git worktrees share Turborepo's local cache. A cache hit can restore .next from
# the canonical checkout into a release worktree so HTML/static verify passes
# while `next start` under demo-current fails (502 / upstream down). Force a real
# build for every release deploy.
if _is_release_build; then
    echo "-- release build: forcing turbo rebuild (no shared worktree cache hit) --"
    export TURBO_FORCE=1
    rm -rf "${DEMO_DIR}/.next"
    pnpm exec turbo run build --filter=@juli/demo --force
else
    pnpm build:demo
fi

if [ ! -f "${DEMO_DIR}/.next/server/app/decisions.html" ]; then
    echo "FAIL: /decisions route not built (.next/server/app/decisions.html missing)" >&2
    exit 1
fi

if [ ! -f "${DEMO_DIR}/.next/server/app/index.html" ]; then
    echo "FAIL: home route not built (.next/server/app/index.html missing)" >&2
    exit 1
fi

if [ ! -d "${DEMO_DIR}/.next/static" ]; then
    echo "FAIL: hashed static assets missing (.next/static directory not found)" >&2
    exit 1
fi

NEXT_BIN="${DEMO_DIR}/node_modules/.bin/next"
if [ ! -e "${NEXT_BIN}" ]; then
    echo "FAIL: next binary missing at ${NEXT_BIN} (pnpm install did not link apps/demo)" >&2
    exit 1
fi

echo "PASS: Demo home and /decisions routes built (mock mode, no API dependency)"

VERIFY_STATIC="${REPO_ROOT}/infra/scripts/verify-demo-static-assets.sh"
if [ -x "${VERIFY_STATIC}" ]; then
    echo "-- verify static asset references --"
    "${VERIFY_STATIC}"
fi
