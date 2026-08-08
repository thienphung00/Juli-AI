#!/usr/bin/env bash
# Verify that a Demo release directory carries a runnable, already-built app.
#
# THIS SCRIPT NO LONGER BUILDS ANYTHING (#837, PRD #820, ADR-058).
#
# It used to run `pnpm install --frozen-lockfile` and `turbo run build` here, on a
# 2 vCPU / 4 GB box, in the middle of a release. Both now run in CI
# (.github/workflows/release.yml -> app-release-artifact), which packages the built
# output together with a production dependency tree resolved there. The server's
# job is to start processes, never to compile.
#
# So the checks below are the same checks as before, doing a different job: they no
# longer confirm that a build just succeeded, they confirm that the artifact placed
# in this directory is complete and runnable before anything is cut over to it. A
# missing .next or a missing `next` binary now means the artifact was never placed,
# not that the build failed.
#
# Placing the artifact into the release directory is #838/#841; #844 retires this
# script once the combined path has completed a real release.
#
# Usage (on the VPS or locally):
#   ./infra/scripts/build-demo.sh
#   REPO_ROOT=~/releases/<sha> ./infra/scripts/build-demo.sh
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

echo "== Juli Demo release verification (apps/demo, mock mode) =="
echo "-- no build runs here; the artifact is built in CI (#837) --"

if [ ! -f "${DEMO_DIR}/.next/server/app/decisions.html" ]; then
    echo "FAIL: /decisions route missing from the artifact (.next/server/app/decisions.html)" >&2
    echo "The artifact is built in CI and placed here by the release delivery step (#838)." >&2
    exit 1
fi

if [ ! -f "${DEMO_DIR}/.next/server/app/index.html" ]; then
    echo "FAIL: home route missing from the artifact (.next/server/app/index.html)" >&2
    exit 1
fi

if [ ! -d "${DEMO_DIR}/.next/static" ]; then
    echo "FAIL: hashed static assets missing (.next/static directory not found)" >&2
    exit 1
fi

NEXT_BIN="${DEMO_DIR}/node_modules/.bin/next"
if [ ! -e "${NEXT_BIN}" ]; then
    echo "FAIL: next binary missing at ${NEXT_BIN} — the artifact did not ship its production dependency tree (ADR-058)" >&2
    exit 1
fi

echo "PASS: Demo artifact is complete and runnable (home + /decisions, mock mode)"

VERIFY_STATIC="${REPO_ROOT}/infra/scripts/verify-demo-static-assets.sh"
if [ -x "${VERIFY_STATIC}" ]; then
    echo "-- verify static asset references --"
    "${VERIFY_STATIC}"
fi
