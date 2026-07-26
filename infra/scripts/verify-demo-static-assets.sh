#!/usr/bin/env bash
# Verify Demo static assets referenced in built HTML exist on disk (Issue #499).
#
# Parses home and /decisions route HTML from a Next.js production build and
# asserts every referenced /_next/static/*.css and *.js file is present locally.
# Reuses the App Review build-frontend-review.sh HTML→chunk existence pattern.
#
# Usage:
#   ./infra/scripts/verify-demo-static-assets.sh
#   DEMO_DIR=/path/to/apps/demo ./infra/scripts/verify-demo-static-assets.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
DEMO_DIR="${DEMO_DIR:-${REPO_ROOT}/apps/demo}"
NEXT_DIR="${DEMO_DIR}/.next"

pass=0
fail=0

ok()   { echo "PASS: $1"; pass=$((pass + 1)); }
bad()  { echo "FAIL: $1" >&2; fail=$((fail + 1)); }

discover_static_assets() {
    grep -oE '/_next/static/[^"'"'"']+\.(css|js)' "$1" 2>/dev/null | sort -u || true
}

asset_disk_path() {
    local asset_url="$1"
    printf '%s%s' "${NEXT_DIR}" "${asset_url#/_next}"
}

verify_route() {
    local route="$1"
    local html_file="$2"
    local route_missing=""
    local asset_count=0

    if [ ! -f "${html_file}" ]; then
        bad "${route} HTML missing (${html_file})"
        return
    fi

    while IFS= read -r asset_url; do
        [ -n "${asset_url}" ] || continue
        asset_count=$((asset_count + 1))
        disk_path="$(asset_disk_path "${asset_url}")"
        if [ ! -f "${disk_path}" ]; then
            route_missing="${asset_url}"
            break
        fi
    done < <(discover_static_assets "${html_file}")

    if [ -n "${route_missing}" ]; then
        bad "${route} HTML references missing asset ${route_missing}"
    elif [ "${asset_count}" -eq 0 ]; then
        bad "${route} HTML did not reference any /_next/static CSS or JS assets"
    else
        ok "${route} HTML — all ${asset_count} referenced static assets exist on disk"
    fi
}

echo "== Juli Demo static asset integrity =="
echo "demo build: ${DEMO_DIR}"
echo

verify_route "/" "${NEXT_DIR}/server/app/index.html"
verify_route "/decisions" "${NEXT_DIR}/server/app/decisions.html"

echo
echo "== summary: ${pass} passed, ${fail} failed =="
[ "${fail}" -eq 0 ]
