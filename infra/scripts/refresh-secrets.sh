#!/usr/bin/env bash
# Periodic secret synchronization: fetch latest values, compare with on-disk env
# files, and restart only the affected systemd unit(s) when content changes.
#
# Intended for systemd timer (daily). Unlike a bare fetch-secrets.sh + restart,
# this avoids unnecessary service restarts when secrets are unchanged.
#
# Note: NEXT_PUBLIC_* values are baked at frontend build time. A change to
# juli/web/production requires redeploy (deploy-release.sh) for the browser to
# see new NEXT_PUBLIC_* values — restarting juli-web alone is not sufficient.
#
# Usage (on the VPS, as root):
#   ./infra/scripts/refresh-secrets.sh
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "FAIL: run as root: sudo $0" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FETCH_SCRIPT="${SCRIPT_DIR}/fetch-secrets.sh"
API_ENV_FILE="/etc/juli/api.env"
WEB_ENV_FILE="/etc/juli/web.env"
API_TMP="$(mktemp /etc/juli/.api.env.XXXXXX)"
WEB_TMP="$(mktemp /etc/juli/.web.env.XXXXXX)"

cleanup() {
    rm -f "${API_TMP}" "${WEB_TMP}"
}
trap cleanup EXIT

if [ ! -x "${FETCH_SCRIPT}" ]; then
    echo "FAIL: ${FETCH_SCRIPT} is missing or not executable." >&2
    exit 1
fi

# Reuse fetch-secrets.sh logic by overriding destination paths via a subshell helper.
fetch_to() {
  # $1 = secret id, $2 = destination temp path
  local secret_id="$1" dest="$2"
  AWS_REGION="${AWS_REGION:-us-east-2}"
  AWS_CONFIG_FILE="${AWS_CONFIG_FILE:-/etc/aws/config}"
  AWS_PROFILE="${AWS_PROFILE:-juli-vps-secrets-reader}"
  export AWS_CONFIG_FILE AWS_PROFILE AWS_REGION

  aws secretsmanager get-secret-value \
      --region "${AWS_REGION}" \
      --secret-id "${secret_id}" \
      --query SecretString \
      --output text \
    | python3 -c '
import json
import sys

data = json.load(sys.stdin)
if not isinstance(data, dict) or not data:
    sys.exit("secret JSON must be a non-empty object")
for key, value in data.items():
    if value is None:
        sys.exit(f"secret key {key!r} must not be null")
    print(f"{key}={value}")
' > "${dest}"
  chown root:root "${dest}"
  chmod 600 "${dest}"
}

echo "== refresh-secrets: checking for secret updates =="

if ! fetch_to "${API_SECRET_ID:-juli/api/production}" "${API_TMP}"; then
    echo "FAIL: could not fetch juli/api/production." >&2
    exit 1
fi
if ! fetch_to "${WEB_SECRET_ID:-juli/web/production}" "${WEB_TMP}"; then
    echo "FAIL: could not fetch juli/web/production." >&2
    exit 1
fi

api_changed=false
web_changed=false

if [ ! -f "${API_ENV_FILE}" ] || ! cmp -s "${API_ENV_FILE}" "${API_TMP}"; then
    api_changed=true
fi
if [ ! -f "${WEB_ENV_FILE}" ] || ! cmp -s "${WEB_ENV_FILE}" "${WEB_TMP}"; then
    web_changed=true
fi

if [ "${api_changed}" = false ] && [ "${web_changed}" = false ]; then
    echo "No secret changes detected — services left running."
    exit 0
fi

if [ "${api_changed}" = true ]; then
    mv -f "${API_TMP}" "${API_ENV_FILE}"
    echo "Updated ${API_ENV_FILE} — restarting juli-api."
    systemctl restart juli-api
fi

if [ "${web_changed}" = true ]; then
    mv -f "${WEB_TMP}" "${WEB_ENV_FILE}"
    echo "Updated ${WEB_ENV_FILE} — restarting juli-web."
    echo "WARN: if NEXT_PUBLIC_* changed, run deploy-release.sh to rebuild the frontend." >&2
    systemctl restart juli-web
fi

echo "== refresh-secrets: complete =="
