#!/usr/bin/env bash
# Build the App Review frontend with UI-only login baked in.
#
# NEXT_PUBLIC_* values are embedded at build time — restarting juli-web alone
# cannot pick up a new build. Always run this before restart.
#
# Usage (on the VPS):
#   cd ~/Juli-AI-v2
#   ./infra/deploy/build-frontend-review.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WEB_DIR="${REPO_ROOT}/web"
ENV_FILE="${WEB_DIR}/.env.production"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Missing ${ENV_FILE}" >&2
    echo "Copy infra/deploy/env/web.env.example to web/.env.production first." >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
source "${ENV_FILE}"
set +a

export NEXT_PUBLIC_UI_ONLY=1

echo "== Juli App Review frontend build =="
echo "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL:-<unset>}"
echo "NEXT_PUBLIC_UI_ONLY=${NEXT_PUBLIC_UI_ONLY}"

cd "${WEB_DIR}"
npm ci
rm -rf .next
npm run build

login_chunk="$(find .next/static/chunks/app/login -name 'page-*.js' -print -quit || true)"
if [ -z "${login_chunk}" ]; then
    echo "FAIL: no login page chunk under .next/static/chunks/app/login/" >&2
    exit 1
fi

if ! grep -q 'Đăng nhập demo\|Tiếp tục vào ứng dụng' "${login_chunk}"; then
    echo "FAIL: login chunk missing demo login markers" >&2
    echo "Check ${ENV_FILE} and rebuild." >&2
    exit 1
fi

echo "PASS: login chunk has demo login entry ($(basename "${login_chunk}"))"
