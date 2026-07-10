#!/usr/bin/env bash
# App Review deployment smoke test (Phase 2.5, issue #253).
#
# Proves review readiness for TikTok App Review: DNS, TLS, frontend load,
# backend health, and the OAuth callback route. This is a review-only check —
# no production users, no production traffic, and no persistent business data
# are required to pass.
#
# Usage:
#   ./infra/scripts/smoke-test.sh
#   ./infra/scripts/smoke-test.sh --dns-tls-only   # Issue #256 — no upstream apps required
#   APP_DOMAIN=app-juli.com API_DOMAIN=api.app-juli.com ./infra/scripts/smoke-test.sh
set -euo pipefail

DNS_TLS_ONLY=false
for arg in "$@"; do
    case "${arg}" in
        --dns-tls-only) DNS_TLS_ONLY=true ;;
        -h|--help)
            echo "Usage: $0 [--dns-tls-only]"
            exit 0
            ;;
    esac
done

APP_DOMAIN="${APP_DOMAIN:-app-juli.com}"
API_DOMAIN="${API_DOMAIN:-api.app-juli.com}"
CALLBACK_PATH="/v1/auth/tiktok/callback"

pass=0
fail=0

ok()   { echo "PASS: $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL: $1"; fail=$((fail + 1)); }

echo "== Juli App Review smoke test =="
if [ "${DNS_TLS_ONLY}" = true ]; then
    echo "mode: DNS + TLS only (issue #256 — upstream apps may be down)"
fi
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

if [ "${DNS_TLS_ONLY}" = true ]; then
    echo "Skipping upstream checks (deploy apps in #257/#258, then run without --dns-tls-only)."
else
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

    # 6. Login page chunk loads and contains demo login markers.
    login_html="$(curl -sS "https://${APP_DOMAIN}/login")"
    login_page_chunk="$(printf '%s' "${login_html}" | grep -oE '/_next/static/chunks/app/login/page-[^"]+\.js' | head -1 || true)"
    if [ -z "${login_page_chunk}" ]; then
        bad "login HTML did not reference app/login/page chunk"
    else
        login_chunk_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${APP_DOMAIN}${login_page_chunk}")"
        if [ "${login_chunk_code}" != "200" ]; then
            bad "login chunk ${login_page_chunk} returned ${login_chunk_code} (stale build — run ./infra/scripts/build-frontend-review.sh && sudo systemctl restart juli-web)"
        else
            login_chunk_body="$(curl -sS "https://${APP_DOMAIN}${login_page_chunk}")"
            if printf '%s' "${login_chunk_body}" | grep -qE 'loginAsReviewer|Đăng nhập demo|Tiếp tục'; then
                ok "login serves demo entry"
            else
                bad "login chunk missing demo markers (rebuild with ./infra/scripts/build-frontend-review.sh)"
            fi
        fi
    fi

    # 7. Home route chunks load (stale partial builds serve login but blank / after auth).
    home_html="$(curl -sS "https://${APP_DOMAIN}/")"
    home_page_chunk="$(printf '%s' "${home_html}" | grep -oE '/_next/static/chunks/app/page-[^"]+\.js' | head -1 || true)"
    if [ -z "${home_page_chunk}" ]; then
        bad "home HTML did not reference app/page chunk"
    else
        home_chunk_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${APP_DOMAIN}${home_page_chunk}")"
        if [ "${home_chunk_code}" != "200" ]; then
            bad "home chunk ${home_page_chunk} returned ${home_chunk_code} (stale build — run ./infra/scripts/build-frontend-review.sh && sudo systemctl restart juli-web)"
        else
            ok "home route chunk loads"
        fi
    fi

    stale_chunk=""
    while IFS= read -r chunk_path; do
        [ -n "${chunk_path}" ] || continue
        chunk_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${APP_DOMAIN}${chunk_path}")"
        if [ "${chunk_code}" != "200" ]; then
            stale_chunk="${chunk_path} (${chunk_code})"
            break
        fi
    done < <(printf '%s' "${home_html}" | grep -oE '/_next/static/chunks/[^"]+\.js' | sort -u)
    if [ -n "${stale_chunk}" ]; then
        bad "home HTML references stale chunk ${stale_chunk} (rebuild with ./infra/scripts/build-frontend-review.sh)"
    else
        ok "all home JS chunks return 200"
    fi

    # 8. CORS allows the review frontend origin (issue #261).
    cors_header="$(curl -sSI -H "Origin: https://${APP_DOMAIN}" "https://${API_DOMAIN}/health" \
        | grep -i '^access-control-allow-origin:' || true)"
    if printf '%s' "${cors_header}" | grep -qi "https://${APP_DOMAIN}"; then
        ok "CORS allows https://${APP_DOMAIN}"
    else
        bad "CORS does not allow https://${APP_DOMAIN} (set CORS_ALLOW_ORIGINS on VPS and restart juli-api)"
    fi
fi

echo
echo "== summary: ${pass} passed, ${fail} failed =="
echo "review-only: no production users or persistent business data required."
[ "${fail}" -eq 0 ]
