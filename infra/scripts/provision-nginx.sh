#!/usr/bin/env bash
# Install App Review Nginx vhosts on the review VPS (Issue #256).
#
# Copies frontend/backend vhost configs from this repo into /etc/nginx and reloads.
# Run on the VPS after DNS A records point at the host and nginx is installed.
#
# ONE-TIME UPSTREAM INDIRECTION (#839). demo.app-juli.com.conf no longer defines its own
# upstream: it `include`s /etc/nginx/juli/demo-upstream.conf, a file the Demo deploy owns
# and replaces atomically at cutover. That include is an explicit filename, so if the file
# is absent nginx refuses to load EVERY site, not just Demo. This script therefore seeds it
# BEFORE installing any vhost — and never overwrites an existing one, because the existing
# one is what is currently serving.
#
# Usage (on VPS):
#   sudo ./infra/scripts/provision-nginx.sh
#   REPO_ROOT=~/Juli-AI-v2 sudo ./infra/scripts/provision-nginx.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
NGINX_SRC="${REPO_ROOT}/infra/nginx"
SITES_AVAILABLE="/etc/nginx/sites-available"
SITES_ENABLED="/etc/nginx/sites-enabled"
UPSTREAM_DIR="${NGINX_UPSTREAM_DIR:-/etc/nginx/juli}"
DEMO_UPSTREAM_CONF="${UPSTREAM_DIR}/demo-upstream.conf"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi

# --- Deployment-owned upstream definitions, before the vhosts that include them. ---
mkdir -p "${UPSTREAM_DIR}"
seed="${NGINX_SRC}/demo-upstream.conf"
if [ ! -f "${seed}" ]; then
    echo "Missing seed upstream definition: ${seed}" >&2
    exit 1
fi
if [ -f "${DEMO_UPSTREAM_CONF}" ]; then
    echo "Kept ${DEMO_UPSTREAM_CONF} (already provisioned; it is what is serving now):"
    awk '/server[[:space:]]+127\.0\.0\.1:/ {print "  " $0}' "${DEMO_UPSTREAM_CONF}"
else
    install -m 0644 "${seed}" "${DEMO_UPSTREAM_CONF}"
    echo "Seeded ${DEMO_UPSTREAM_CONF} from ${seed}"
fi

for conf in app-juli.com.conf api.app-juli.com.conf demo.app-juli.com.conf; do
    src="${NGINX_SRC}/${conf}"
    if [ ! -f "${src}" ]; then
        echo "Missing nginx config: ${src}" >&2
        exit 1
    fi
    install -m 0644 "${src}" "${SITES_AVAILABLE}/${conf}"
    ln -sf "${SITES_AVAILABLE}/${conf}" "${SITES_ENABLED}/${conf}"
    echo "Installed ${conf}"
done

# Drop default site if present — avoids server_name conflicts on port 80.
if [ -e "${SITES_ENABLED}/default" ]; then
    rm -f "${SITES_ENABLED}/default"
    echo "Removed default site"
fi

mkdir -p /var/www/certbot
nginx -t
systemctl reload nginx
echo "Nginx reloaded. Next: certbot --nginx (see docs/runbooks/vps-wiring-runbook.md)"
