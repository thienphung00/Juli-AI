#!/usr/bin/env bash
# App Review deployment smoke test (Phase 2.5, issue #253).
#
# Proves review readiness for TikTok App Review: DNS, TLS, frontend load,
# backend health, and the OAuth callback route. This is a review-only check —
# no production users, no production traffic, and no persistent business data
# are required to pass.
#
# Usage:
#   ./infra/deploy/smoke-test.sh
#   APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/deploy/smoke-test.sh
set -euo pipefail

APP_DOMAIN="${APP_DOMAIN:-app-juli.com}"
API_DOMAIN="${API_DOMAIN:-api.app-juli.com}"
CALLBACK_PATH="/v1/auth/tiktok/callback"

pass=0
fail=0

ok()   { echo "PASS: $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL: $1"; fail=$((fail + 1)); }

echo "== Juli App Review smoke test =="
echo "frontend: https://${APP_DOMAIN}  backend: https://${API_DOMAIN}"
echo

# 1. DNS resolves for both domains.
for domain in "${APP_DOMAIN}" "${API_DOMAIN}"; do
    if [ -n "$(dig +short "${domain}" A)" ]; then
        ok "DNS resolves for ${domain}"
    else
        bad "DNS does not resolve for ${domain}"
    fi
done

# 2. TLS terminates (HTTPS handshake succeeds).
for domain in "${APP_DOMAIN}" "${API_DOMAIN}"; do
    if curl -sSf -o /dev/null "https://${domain}" 2>/dev/null \
        || curl -sS -o /dev/null "https://${domain}"; then
        ok "TLS handshake succeeds for ${domain}"
    else
        bad "TLS handshake failed for ${domain}"
    fi
done

# 3. Frontend loads over HTTPS.
if curl -sSf -o /dev/null "https://${APP_DOMAIN}/"; then
    ok "frontend loads at https://${APP_DOMAIN}/"
else
    bad "frontend did not load at https://${APP_DOMAIN}/"
fi

# 4. Backend health returns 2xx.
health_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${API_DOMAIN}/health")"
if [ "${health_code}" -ge 200 ] && [ "${health_code}" -lt 300 ]; then
    ok "/health returned ${health_code}"
else
    bad "/health returned ${health_code}"
fi

# 5. OAuth callback route exists and does not 5xx on missing params.
cb_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${API_DOMAIN}${CALLBACK_PATH}")"
if [ "${cb_code}" -lt 500 ]; then
    ok "OAuth callback ${CALLBACK_PATH} returned ${cb_code} (no 5xx)"
else
    bad "OAuth callback ${CALLBACK_PATH} returned ${cb_code}"
fi

echo
echo "== summary: ${pass} passed, ${fail} failed =="
echo "review-only: no production users or persistent business data required."
[ "${fail}" -eq 0 ]
