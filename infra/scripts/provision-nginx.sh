#!/usr/bin/env bash
# Install App Review Nginx vhosts on the review VPS (Issue #256).
#
# Copies frontend/backend vhost configs from this repo into /etc/nginx and reloads.
# Run on the VPS after DNS A records point at the host and nginx is installed.
#
# Usage (on VPS):
#   sudo ./infra/scripts/provision-nginx.sh
#   REPO_ROOT=~/Juli-AI-v2 sudo ./infra/scripts/provision-nginx.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
NGINX_SRC="${REPO_ROOT}/infra/nginx"
SITES_AVAILABLE="/etc/nginx/sites-available"
SITES_ENABLED="/etc/nginx/sites-enabled"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root: sudo $0" >&2
    exit 1
fi

for conf in app-juli.com.conf api.app-juli.com.conf; do
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
