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
NGINX_UPSTREAM_DIR="${NGINX_UPSTREAM_DIR:-/etc/nginx/juli}"
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

# Which unit is ACTUALLY serving the API (issue #1201).
#
# deploy.sh runs blue/green: each build starts as a TRANSIENT
# `juli-api-candidate-<port>` unit and the nginx include decides which slot is
# live. `juli-api.service` is the bootstrap unit, not the steady-state one — so
# `systemctl restart juli-api` restarted something that was frequently not
# serving traffic (and often `inactive`), reported success, and left the live
# process running with the OLD environment until the next deploy replaced it.
#
# Observed 2026-08-18: AGENT_WORKFLOWS_ENABLED=1 was written here and this
# script reported "restarting juli-api", yet the process serving
# api.app-juli.com had ~4-day-old environment and never saw it. The same would
# be true of a rotated database password or JWT secret — the rotation appears
# to succeed while production keeps the old value. This runs on a daily timer,
# so the failure is silent and recurring.
live_api_units() {
    local conf="${NGINX_UPSTREAM_DIR}/api-upstream.conf" port candidate
    if [ -f "${conf}" ]; then
        port="$(awk 'match($0, /server[[:space:]]+127\.0\.0\.1:[0-9]+;/) {
            s = substr($0, RSTART, RLENGTH); sub(/.*:/, "", s); sub(/;/, "", s); print s; exit }' "${conf}")"
        candidate="juli-api-candidate-${port}.service"
        if [ -n "${port}" ] && systemctl is-active --quiet "${candidate}"; then
            echo "${candidate}"
            return 0
        fi
    fi
    # No live candidate: a fresh bootstrap before the first deploy, where the
    # persistent unit really is what serves.
    echo "juli-api.service"
}

# Worker and beat read the SAME env file and were never restarted at all, so
# they held stale secrets until someone bounced them by hand.
API_ENV_CONSUMERS=(juli-celery-worker juli-celery-beat)

if [ "${api_changed}" = true ]; then
    mv -f "${API_TMP}" "${API_ENV_FILE}"
    api_unit="$(live_api_units)"
    echo "Updated ${API_ENV_FILE} — restarting ${api_unit} and ${API_ENV_CONSUMERS[*]}."
    systemctl restart "${api_unit}"
    for unit in "${API_ENV_CONSUMERS[@]}"; do
        systemctl restart "${unit}" || echo "WARN: ${unit} failed to restart" >&2
    done

    # A rotation that silently no-ops is the whole bug, so verify rather than
    # trusting that issuing a restart was enough. Compares a key from the new
    # file against the live process's own environment.
    probe_key="$(grep -m1 -oE '^[A-Z_][A-Z0-9_]*=' "${API_ENV_FILE}" | tr -d '=')"
    if [ -n "${probe_key}" ]; then
        pid="$(systemctl show -p MainPID --value "${api_unit}" 2>/dev/null || echo 0)"
        expected="$(grep -m1 "^${probe_key}=" "${API_ENV_FILE}")"
        if [ "${pid}" != "0" ] && [ -r "/proc/${pid}/environ" ]; then
            if ! tr '\0' '\n' < "/proc/${pid}/environ" | grep -qxF "${expected}"; then
                echo "FAIL: ${api_unit} (pid ${pid}) does not reflect the updated ${API_ENV_FILE}" >&2
                exit 1
            fi
            echo "Verified ${api_unit} picked up the updated environment."
        else
            echo "WARN: could not read /proc/${pid}/environ to verify ${api_unit}" >&2
        fi
    fi
fi

if [ "${web_changed}" = true ]; then
    mv -f "${WEB_TMP}" "${WEB_ENV_FILE}"
    echo "Updated ${WEB_ENV_FILE} — restarting juli-web."
    echo "WARN: if NEXT_PUBLIC_* changed, run deploy-release.sh to rebuild the frontend." >&2
    systemctl restart juli-web
fi

echo "== refresh-secrets: complete =="
