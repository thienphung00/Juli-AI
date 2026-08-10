#!/usr/bin/env bash
# Exit gate (issue #898 / ADR-061 §2b): assert infra/nginx/*.conf parses on the nginx
# version actually running on the review VPS.
#
# Precedent (#882, "fix(infra): nginx configs must parse on the nginx we actually run"):
# the vhosts previously used the `http2 on;` directive form, which only nginx >= 1.25.1
# accepts — the review VPS runs Ubuntu's packaged nginx 1.24.0, so `nginx -t` failed on
# the live host and the Demo cutover correctly refused to reload. That bug was caught by
# a human running `nginx -t` on the VPS after the fact; this script makes the same check
# a CI gate so drift is caught on the PR, not after a certbot renewal restarts nginx and
# it fails to come back up.
#
# GitHub Actions' ubuntu-latest runner is the same Ubuntu LTS family as the review VPS
# (ADR-057), so `apt-get install nginx` on the runner installs the SAME packaged nginx
# build the VPS runs — no separate version pin to maintain or let drift silently.
#
# This assembles the exact files infra/nginx/provision-nginx.sh installs into their real
# absolute install paths (/etc/nginx/sites-enabled, /etc/nginx/juli/*, /etc/nginx/conf.d)
# and runs `nginx -t` against them, because the vhosts `include` those paths as absolute
# paths (matching the real deployment) — there is no way to validate the literal
# committed files without those exact paths existing somewhere. This never touches the
# review VPS: it runs only on the disposable CI runner, which is destroyed after the job
# (see infra/nginx/rate-limits.conf and the issue #898 PR description — config artifact
# only, applying it to the live host is separate human follow-up).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
NGINX_SRC="${REPO_ROOT}/infra/nginx"

if ! command -v nginx >/dev/null 2>&1; then
    echo "nginx not found on PATH. On Ubuntu: sudo apt-get update && sudo apt-get install -y nginx-core" >&2
    exit 1
fi

echo "nginx version under test:"
nginx -v

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

# --- Deployment-owned upstream includes (seeded once by provision-nginx.sh; #839/#843).
$SUDO mkdir -p /etc/nginx/juli
for lane in api demo landing; do
    $SUDO install -m 0644 "${NGINX_SRC}/${lane}-upstream.conf" "/etc/nginx/juli/${lane}-upstream.conf"
done

# --- Rate-limit zones (http context; #898/ADR-061 §2b) — see provision-nginx.sh.
$SUDO mkdir -p /etc/nginx/conf.d
$SUDO install -m 0644 "${NGINX_SRC}/rate-limits.conf" /etc/nginx/conf.d/rate-limits.conf

# --- Vhosts.
$SUDO mkdir -p /etc/nginx/sites-available /etc/nginx/sites-enabled
$SUDO rm -f /etc/nginx/sites-enabled/default
for conf in app-juli.com.conf api.app-juli.com.conf demo.app-juli.com.conf; do
    $SUDO install -m 0644 "${NGINX_SRC}/${conf}" "/etc/nginx/sites-available/${conf}"
    $SUDO ln -sf "/etc/nginx/sites-available/${conf}" "/etc/nginx/sites-enabled/${conf}"
done

# --- Throwaway self-signed certs at the exact paths the vhosts reference. `nginx -t`
# loads ssl_certificate/ssl_certificate_key while validating the http block, so
# something must exist there; these are generated fresh on the disposable runner and are
# never the review VPS's real certbot-issued certificates.
for domain in api.app-juli.com app-juli.com demo.app-juli.com; do
    $SUDO mkdir -p "/etc/letsencrypt/live/${domain}"
    if [ ! -f "/etc/letsencrypt/live/${domain}/fullchain.pem" ]; then
        $SUDO openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
            -keyout "/etc/letsencrypt/live/${domain}/privkey.pem" \
            -out "/etc/letsencrypt/live/${domain}/fullchain.pem" \
            -subj "/CN=${domain}" >/dev/null 2>&1
    fi
done
$SUDO mkdir -p /var/www/certbot

CANDIDATE_CONFIG="/etc/nginx/nginx.conf"
echo "Running: nginx -t -c ${CANDIDATE_CONFIG}"
$SUDO nginx -t -c "${CANDIDATE_CONFIG}"
