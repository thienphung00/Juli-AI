#!/usr/bin/env bash
# Build the App Review frontend with UI-only login baked in.
#
# NEXT_PUBLIC_* values are embedded at build time — restarting juli-web alone
# cannot pick up a new build. Always run this before restart.
#
# Usage (on the VPS):
#   cd ~/Juli-AI-v2
#   ./infra/scripts/build-frontend-review.sh
set -euo pipefail

# deploy-release.sh sets REPO_ROOT to the release worktree; manual runs default to
# the checkout that contains this script (usually ~/Juli-AI-v2).
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
WEB_DIR="${REPO_ROOT}/apps/dashboard"
ENV_FILE="${WEB_DIR}/.env.production"

if [ ! -f "${ENV_FILE}" ]; then
    echo "Missing ${ENV_FILE}" >&2
    echo "Copy infra/scripts/env/web.env.example to apps/dashboard/.env.production first." >&2
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

# Next.js 16 (Turbopack) emits flat hashed client chunks — not
# .next/static/chunks/app/login/page-*.js. Validate via built HTML + chunk scan.
if [ ! -f .next/server/app/login.html ]; then
    echo "FAIL: login route not built (.next/server/app/login.html missing)" >&2
    exit 1
fi

login_chunk=""
while IFS= read -r chunk; do
    if grep -qE 'loginAsReviewer|Đăng nhập demo|Tiếp tục' "${chunk}"; then
        login_chunk="${chunk}"
        break
    fi
done < <(find .next/static/chunks -maxdepth 1 -name '*.js' -type f 2>/dev/null)

if [ -z "${login_chunk}" ]; then
    echo "FAIL: no client chunk contains demo login markers" >&2
    echo "Check ${ENV_FILE} and rebuild." >&2
    exit 1
fi

if [ ! -f .next/server/app/index.html ]; then
    echo "FAIL: home route not built (.next/server/app/index.html missing)" >&2
    exit 1
fi

missing_home_chunk=""
while IFS= read -r chunk_path; do
    [ -n "${chunk_path}" ] || continue
    chunk_file=".next/static/chunks/$(basename "${chunk_path}")"
    if [ ! -f "${chunk_file}" ]; then
        missing_home_chunk="${chunk_path}"
        break
    fi
done < <(grep -oE '/_next/static/chunks/[^"]+\.js' .next/server/app/index.html | sort -u)

if [ -n "${missing_home_chunk}" ]; then
    echo "FAIL: home HTML references missing chunk ${missing_home_chunk}" >&2
    exit 1
fi

echo "PASS: login chunk has demo login entry ($(basename "${login_chunk}"))"
echo "PASS: home route HTML and client chunks built"
