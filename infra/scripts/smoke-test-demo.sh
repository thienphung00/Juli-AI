#!/usr/bin/env bash
# Demo deployment smoke test (Phase 2.6, Issue #406).
#
# Proves Demo readiness for demo.app-juli.com: DNS, TLS, and the mandatory
# /decisions route. Mock mode requires no backend credentials or API availability.
#
# Usage:
#   ./infra/scripts/smoke-test-demo.sh
#   DEMO_DOMAIN=demo.app-juli.com ./infra/scripts/smoke-test-demo.sh
#   ./infra/scripts/smoke-test-demo.sh --dns-tls-only   # before juli-demo is up
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

DEMO_DOMAIN="${DEMO_DOMAIN:-demo.app-juli.com}"
DEMO_PORT="${DEMO_PORT:-3001}"

pass=0
fail=0

ok()   { echo "PASS: $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL: $1"; fail=$((fail + 1)); }

echo "== Juli Demo smoke test =="
if [ "${DNS_TLS_ONLY}" = true ]; then
    echo "mode: DNS + TLS only (upstream juli-demo may be down)"
fi
echo "demo: https://${DEMO_DOMAIN}"
echo

# 1. DNS resolves.
if [ -n "$(dig +short "${DEMO_DOMAIN}" A)" ]; then
    ok "DNS resolves for ${DEMO_DOMAIN}"
else
    bad "DNS does not resolve for ${DEMO_DOMAIN}"
fi

# 2. TLS terminates.
if curl -sSf -o /dev/null "https://${DEMO_DOMAIN}" 2>/dev/null \
    || curl -sS -o /dev/null "https://${DEMO_DOMAIN}"; then
    ok "TLS handshake succeeds for ${DEMO_DOMAIN}"
else
    bad "TLS handshake failed for ${DEMO_DOMAIN}"
fi

if [ "${DNS_TLS_ONLY}" = true ]; then
    echo "Skipping upstream checks (provision juli-demo, then run without --dns-tls-only)."
else
    # 3. Demo home loads over HTTPS.
    if curl -sSf -o /dev/null "https://${DEMO_DOMAIN}/"; then
        ok "Demo home loads at https://${DEMO_DOMAIN}/"
    else
        bad "Demo home did not load at https://${DEMO_DOMAIN}/"
    fi

    # 4. Mandatory /decisions route returns 2xx.
    decisions_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${DEMO_DOMAIN}/decisions")"
    if [ "${decisions_code}" -ge 200 ] && [ "${decisions_code}" -lt 300 ]; then
        ok "/decisions returned ${decisions_code}"
    else
        bad "/decisions returned ${decisions_code}"
    fi

    # 5. Local upstream health (optional cross-check when run on VPS).
    local_code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${DEMO_PORT}/decisions" 2>/dev/null || echo "000")"
    if [ "${local_code}" -ge 200 ] && [ "${local_code}" -lt 300 ]; then
        ok "local juli-demo upstream /decisions returned ${local_code}"
    else
        echo "INFO: local upstream check skipped or failed (local_code=${local_code}) — public HTTPS checks are authoritative."
    fi

    # 6. Discover critical CSS/JS from HTML and assert all return 200 (issue #499).
    # Asset types: .css stylesheets and .js client bundles under /_next/static/.
    discover_demo_static_assets() {
        printf '%s' "$1" | grep -oE '/_next/static/[^"'"'"']+\.(css|js)' | sort -u
    }

    check_route_static_assets() {
        local route="$1"
        local html="$2"
        local stale_asset=""
        local asset_count=0

        while IFS= read -r asset_path; do
            [ -n "${asset_path}" ] || continue
            asset_count=$((asset_count + 1))
            asset_code="$(curl -s -o /dev/null -w '%{http_code}' "https://${DEMO_DOMAIN}${asset_path}")"
            if [ "${asset_code}" != "200" ]; then
                stale_asset="${asset_path} (${asset_code})"
                break
            fi
        done < <(discover_demo_static_assets "${html}")

        if [ "${asset_count}" -eq 0 ]; then
            bad "${route} HTML did not reference any /_next/static CSS or JS assets"
        elif [ -n "${stale_asset}" ]; then
            bad "${route} HTML references stale asset ${stale_asset} (run ./infra/scripts/deploy-demo-release.sh on the VPS — juli-demo serves ~/releases/demo-current, not ~/Juli-AI-v2)"
        else
            ok "${route} — all ${asset_count} referenced static assets return 200"
        fi
    }

    home_html="$(curl -sS "https://${DEMO_DOMAIN}/")"
    check_route_static_assets "home" "${home_html}"

    decisions_html="$(curl -sS "https://${DEMO_DOMAIN}/decisions")"
    check_route_static_assets "/decisions" "${decisions_html}"
fi

echo
echo "== Summary: ${pass} passed, ${fail} failed =="
if [ "${fail}" -gt 0 ]; then
    exit 1
fi
echo "Demo smoke test passed (mock mode — no backend credentials required)."
