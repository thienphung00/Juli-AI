#!/usr/bin/env bash
# Fetch backend/frontend runtime config from AWS Secrets Manager and write
# systemd-readable env files. Called by deploy-release.sh before every deploy,
# wired as ExecStartPre= on both systemd units, and invoked by refresh-secrets.sh
# for periodic synchronization.
#
# Auth: IAM Roles Anywhere via X.509 client certificate — no static AWS access
# keys, no shared credentials file. Configure /etc/aws/config with
# credential_process (aws_signing_helper) and set AWS_PROFILE below.
#
# Secrets (JSON blob per app):
#   juli/api/production      -> /etc/juli/api.env
#   juli/web/production      -> /etc/juli/web.env
#   juli/frontend/production -> /etc/juli/frontend.env   (OPTIONAL, see below)
#
# Usage (on the VPS, as root):
#   ./infra/scripts/fetch-secrets.sh
#
# Env overrides: AWS_REGION, AWS_CONFIG_FILE, AWS_PROFILE,
#                API_SECRET_ID, WEB_SECRET_ID, FRONTEND_SECRET_ID.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "FAIL: run as root: sudo $0" >&2
    exit 1
fi

AWS_REGION="${AWS_REGION:-us-east-2}"
AWS_CONFIG_FILE="${AWS_CONFIG_FILE:-/etc/aws/config}"
AWS_PROFILE="${AWS_PROFILE:-juli-vps-secrets-reader}"
API_SECRET_ID="${API_SECRET_ID:-juli/api/production}"
WEB_SECRET_ID="${WEB_SECRET_ID:-juli/web/production}"
FRONTEND_SECRET_ID="${FRONTEND_SECRET_ID:-juli/frontend/production}"
API_ENV_FILE="/etc/juli/api.env"
WEB_ENV_FILE="/etc/juli/web.env"
FRONTEND_ENV_FILE="/etc/juli/frontend.env"

export AWS_CONFIG_FILE AWS_PROFILE AWS_REGION

if [ ! -f "${AWS_CONFIG_FILE}" ]; then
    echo "FAIL: ${AWS_CONFIG_FILE} not found." >&2
    echo "Provision IAM Roles Anywhere and /etc/aws/config first — see app-review-runbook.md." >&2
    exit 1
fi

mkdir -p /etc/juli
chmod 700 /etc/juli

fetch_secret_json() {
    # $1 = secret id. Never echo the result — caller consumes it directly.
    aws secretsmanager get-secret-value \
        --region "${AWS_REGION}" \
        --secret-id "$1" \
        --query SecretString \
        --output text
}

write_env_file() {
    # $1 = secret id, $2 = destination path. Values never touch stdout/stderr.
    local secret_id="$1" dest="$2" tmp json
    tmp="$(mktemp /etc/juli/.env.XXXXXX)"

    if ! json="$(fetch_secret_json "${secret_id}")"; then
        rm -f "${tmp}"
        echo "FAIL: could not fetch secret ${secret_id} (region ${AWS_REGION}, profile ${AWS_PROFILE})." >&2
        exit 1
    fi

    if [ -z "${json}" ]; then
        rm -f "${tmp}"
        echo "FAIL: secret ${secret_id} returned an empty payload." >&2
        exit 1
    fi

    if ! printf '%s' "${json}" | python3 -c '
import json
import sys

data = json.load(sys.stdin)
if not isinstance(data, dict) or not data:
    sys.exit("secret JSON must be a non-empty object")
for key, value in data.items():
    if not isinstance(key, str) or not key:
        sys.exit("secret JSON keys must be non-empty strings")
    if value is None:
        sys.exit(f"secret key {key!r} must not be null")
    print(f"{key}={value}")
' > "${tmp}"; then
        rm -f "${tmp}"
        echo "FAIL: secret ${secret_id} is not valid JSON or contains invalid keys." >&2
        exit 1
    fi

    if [ ! -s "${tmp}" ]; then
        rm -f "${tmp}"
        echo "FAIL: secret ${secret_id} produced an empty env file." >&2
        exit 1
    fi

    chown root:root "${tmp}"
    chmod 600 "${tmp}"
    mv -f "${tmp}" "${dest}"
    echo "Wrote $(wc -l < "${dest}") key(s) to ${dest} (values redacted)."
}

# The Landing/Demo server-side secret is OPTIONAL, and that is deliberate.
#
# This script is ExecStartPre= on juli-api and juli-web. write_env_file exits 1
# on a missing secret, so wiring juli/frontend/production in the same way would
# stop the API booting on any host where that secret has not been created yet —
# trading a missing analytics channel for an outage. It warns and continues
# instead; the relay route answers 503 and logs loudly when its token is absent
# (packages/tiktok-events/src/server/handler.ts), which is where that failure
# belongs.
write_env_file_optional() {
    # $1 = secret id, $2 = destination path.
    local secret_id="$1" dest="$2"

    if ! fetch_secret_json "${secret_id}" >/dev/null 2>&1; then
        echo "WARN: optional secret ${secret_id} is unavailable — ${dest} left as-is." >&2
        echo "WARN: the TikTok Events API relay will answer 503 until it exists." >&2
        return 0
    fi

    write_env_file "${secret_id}" "${dest}"
}

echo "== Fetching secrets from AWS Secrets Manager (region ${AWS_REGION}, profile ${AWS_PROFILE}) =="
write_env_file "${API_SECRET_ID}" "${API_ENV_FILE}"
write_env_file "${WEB_SECRET_ID}" "${WEB_ENV_FILE}"
write_env_file_optional "${FRONTEND_SECRET_ID}" "${FRONTEND_ENV_FILE}"
echo "== Done. Restart juli-api/juli-web/juli-landing/juli-demo (or redeploy) to pick up any changes. =="
