#!/usr/bin/env bash
# Install and start the Demo frontend on the review VPS (Issue #406).
#
# Copies juli-demo.service, ensures apps/demo/.env.production exists (mock-only),
# runs the Demo build (pnpm build:demo), and enables systemd on 127.0.0.1:3001.
#
# Usage (on VPS):
#   sudo ./infra/scripts/provision-demo.sh
#   REPO_ROOT=~/Juli-AI-v2 sudo ./infra/scripts/provision-demo.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SYSTEMD_SRC="${REPO_ROOT}/infra/systemd/juli-demo.service"
ENV_EXAMPLE="${REPO_ROOT}/infra/scripts/env/demo.env.example"
ENV_FILE="${REPO_ROOT}/apps/demo/.env.production"
BUILD_SCRIPT="${REPO_ROOT}/infra/scripts/build-demo.sh"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi

if [ ! -f "${SYSTEMD_SRC}" ]; then
    echo "Missing systemd unit: ${SYSTEMD_SRC}" >&2
    exit 1
fi

if [ ! -f "${ENV_FILE}" ]; then
    if [ ! -f "${ENV_EXAMPLE}" ]; then
        echo "Missing env template: ${ENV_EXAMPLE}" >&2
        exit 1
    fi
    cp "${ENV_EXAMPLE}" "${ENV_FILE}"
    echo "Created ${ENV_FILE} from template — mock mode requires no backend credentials."
fi

install -m 0644 "${SYSTEMD_SRC}" /etc/systemd/system/juli-demo.service
systemctl daemon-reload

echo "Building Demo (pnpm build:demo for apps/demo)..."
if [ ! -x "${BUILD_SCRIPT}" ]; then
    chmod +x "${BUILD_SCRIPT}"
fi
"${BUILD_SCRIPT}"

systemctl enable juli-demo
systemctl restart juli-demo
systemctl --no-pager --full status juli-demo || true

echo "juli-demo listening on 127.0.0.1:3001. Next: ./infra/scripts/smoke-test-demo.sh"
