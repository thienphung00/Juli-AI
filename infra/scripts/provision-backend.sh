#!/usr/bin/env bash
# Install and start the App Review backend on the review VPS (Issue #258).
#
# Copies juli-api.service, ensures .env exists from api.env.example, installs
# Python deps in .venv, and enables systemd on 127.0.0.1:8000 (single worker).
#
# App Review envelope: background services out of scope — see app-review-runbook.md.
# Database migrations are skipped unless OAuth/login persistence requires schema.
#
# Usage (on VPS):
#   sudo ./infra/scripts/provision-backend.sh
#   REPO_ROOT=~/Juli-AI-v2 sudo ./infra/scripts/provision-backend.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SYSTEMD_SRC="${REPO_ROOT}/infra/systemd/juli-api.service"
ENV_EXAMPLE="${REPO_ROOT}/infra/scripts/env/api.env.example"
ENV_FILE="${REPO_ROOT}/.env"
VENV="${REPO_ROOT}/.venv"
REQUIREMENTS="${REPO_ROOT}/requirements.txt"

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
    echo "Created ${ENV_FILE} from template — fill DATABASE_URL and secrets on VPS."
fi

if ! grep -q 'CORS_ALLOW_ORIGINS=https://app-juli.com' "${ENV_FILE}"; then
    echo "WARN: ${ENV_FILE} should set CORS_ALLOW_ORIGINS=https://app-juli.com" >&2
fi

if [ ! -d "${VENV}" ]; then
    echo "Creating Python venv at ${VENV}..."
    python3 -m venv "${VENV}"
fi

if [ ! -f "${REQUIREMENTS}" ]; then
    echo "Missing requirements: ${REQUIREMENTS}" >&2
    exit 1
fi

echo "Installing Python dependencies..."
"${VENV}/bin/pip" install -r "${REQUIREMENTS}"
"${VENV}/bin/pip" install -e "${REPO_ROOT}/backend"

install -m 0644 "${SYSTEMD_SRC}" /etc/systemd/system/juli-api.service
systemctl daemon-reload

systemctl enable juli-api
systemctl restart juli-api
systemctl --no-pager --full status juli-api || true

echo "juli-api listening on 127.0.0.1:8000 (single uvicorn worker)."
echo "Verify: curl -sS http://127.0.0.1:8000/health"
echo "Next: APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh"
