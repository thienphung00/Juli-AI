#!/usr/bin/env bash
# Build the Demo frontend (apps/demo) with mock data only.
#
# No backend credentials or NEXT_PUBLIC_API_URL are required — the Demo is
# self-contained. Always run this before restarting juli-demo when code changes.
#
# Usage (on the VPS or locally):
#   cd ~/Juli-AI-v2
#   ./infra/scripts/build-demo.sh
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

echo "== Juli Demo frontend build (apps/demo, mock mode) =="

cd "${REPO_ROOT}"
corepack enable pnpm 2>/dev/null || true
pnpm install --frozen-lockfile --filter @juli/demo...
pnpm build:demo

if [ ! -f "${DEMO_DIR}/.next/server/app/decisions.html" ]; then
    echo "FAIL: /decisions route not built (.next/server/app/decisions.html missing)" >&2
    exit 1
fi

if [ ! -f "${DEMO_DIR}/.next/server/app/index.html" ]; then
    echo "FAIL: home route not built (.next/server/app/index.html missing)" >&2
    exit 1
fi

echo "PASS: Demo home and /decisions routes built (mock mode, no API dependency)"
