#!/usr/bin/env bash
# Install and start the App Review frontend on the review VPS (Issue #257).
#
# Copies juli-web.service, ensures apps/dashboard/.env.production exists, runs the review
# build (npm ci && npm run build with NEXT_PUBLIC_API_URL), and enables systemd.
#
# Usage (on VPS):
#   sudo ./infra/scripts/provision-frontend.sh
#   REPO_ROOT=~/Juli-AI-v2 sudo ./infra/scripts/provision-frontend.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SYSTEMD_SRC="${REPO_ROOT}/infra/systemd/juli-web.service"
ENV_EXAMPLE="${REPO_ROOT}/infra/scripts/env/web.env.example"
ENV_FILE="${REPO_ROOT}/apps/dashboard/.env.production"
BUILD_SCRIPT="${REPO_ROOT}/infra/scripts/build-frontend-review.sh"

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
    echo "Created ${ENV_FILE} from template — verify NEXT_PUBLIC_API_URL on VPS."
fi

if ! grep -q 'NEXT_PUBLIC_API_URL=https://api.app-juli.com' "${ENV_FILE}"; then
    echo "WARN: ${ENV_FILE} should set NEXT_PUBLIC_API_URL=https://api.app-juli.com" >&2
fi

install -m 0644 "${SYSTEMD_SRC}" /etc/systemd/system/juli-web.service
systemctl daemon-reload

echo "Building frontend (npm ci && npm run build)..."
if [ ! -x "${BUILD_SCRIPT}" ]; then
    chmod +x "${BUILD_SCRIPT}"
fi
"${BUILD_SCRIPT}"

systemctl enable juli-web
systemctl restart juli-web
systemctl --no-pager --full status juli-web || true

echo "juli-web listening on 127.0.0.1:3000. Next: ./infra/scripts/smoke-test.sh"
