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
#   juli/api/production -> /etc/juli/api.env
#   juli/web/production -> /etc/juli/web.env
#
# Usage (on the VPS, as root):
#   ./infra/scripts/fetch-secrets.sh
#
# Env overrides: AWS_REGION, AWS_CONFIG_FILE, AWS_PROFILE,
#                API_SECRET_ID, WEB_SECRET_ID.
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
API_ENV_FILE="/etc/juli/api.env"
WEB_ENV_FILE="/etc/juli/web.env"

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

echo "== Fetching secrets from AWS Secrets Manager (region ${AWS_REGION}, profile ${AWS_PROFILE}) =="
write_env_file "${API_SECRET_ID}" "${API_ENV_FILE}"
write_env_file "${WEB_SECRET_ID}" "${WEB_ENV_FILE}"
echo "== Done. Restart juli-api/juli-web (or redeploy) to pick up any changes. =="
