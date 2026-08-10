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
# Every deployable's upstream is a deployment-owned include, seeded ONCE and never
# overwritten afterwards: the installed copy is what is serving right now (#839/#843).
for lane in demo api landing; do
    seed="${NGINX_SRC}/${lane}-upstream.conf"
    target="${UPSTREAM_DIR}/${lane}-upstream.conf"
    if [ ! -f "${seed}" ]; then
        echo "Missing seed upstream definition: ${seed}" >&2
        exit 1
    fi
    if [ -f "${target}" ]; then
        echo "Kept ${target} (already provisioned; it is what is serving now):"
        awk '/server[[:space:]]+127\.0\.0\.1:/ {print "  " $0}' "${target}"
    else
        install -m 0644 "${seed}" "${target}"
        echo "Seeded ${target} from ${seed}"
    fi
done

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

# Inbound rate-limit zones (#898/ADR-061 §2b). `limit_req_zone` must live in the http
# context, so this is a conf.d snippet, not a vhost — Ubuntu's stock nginx.conf already
# `include`s /etc/nginx/conf.d/*.conf inside `http {}`, before sites-enabled/*. Unlike
# the upstream includes above, this is not deployment-owned/cutover state, so it is
# reinstalled (overwritten) on every provisioning run like the vhosts themselves.
RATE_LIMITS_SRC="${NGINX_SRC}/rate-limits.conf"
if [ ! -f "${RATE_LIMITS_SRC}" ]; then
    echo "Missing nginx config: ${RATE_LIMITS_SRC}" >&2
    exit 1
fi
mkdir -p /etc/nginx/conf.d
install -m 0644 "${RATE_LIMITS_SRC}" /etc/nginx/conf.d/rate-limits.conf
echo "Installed rate-limits.conf"

# Drop default site if present — avoids server_name conflicts on port 80.
if [ -e "${SITES_ENABLED}/default" ]; then
    rm -f "${SITES_ENABLED}/default"
    echo "Removed default site"
fi

# Drop pre-provision hand-made vhosts (extensionless names from the initial VPS setup).
# They duplicate the .conf set installed above, and nginx resolves the conflict by
# server-name+include order — on 2026-08-09 the stale Jun-25 files were silently
# serving api/app while the provisioned .conf files were ignored.
for legacy in app-juli.com api.app-juli.com demo.app-juli.com; do
    if [ -e "${SITES_ENABLED}/${legacy}" ]; then
        rm -f "${SITES_ENABLED}/${legacy}"
        echo "Removed legacy duplicate site ${legacy} (superseded by ${legacy}.conf)"
    fi
done

mkdir -p /var/www/certbot
nginx -t
systemctl reload nginx
echo "Nginx reloaded. Next: certbot --nginx (see docs/runbooks/vps-wiring-runbook.md)"
