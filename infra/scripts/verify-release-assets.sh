#!/usr/bin/env bash
# Release asset verification harness (Issue #833, slice P0-DEL-VERIFY of PRD #820).
#
# Given a base URL, fetch each HTML route, discover every stylesheet and script the
# document references, fetch each one, and fail if any is missing or carries a
# trivial/error body in place of real content.
#
# Why body content and not just status: the failure this exists to catch is a release
# missing its built asset files. The page loads, every probe is green, and the styling is
# gone — because the server answers the stylesheet request with a 200 and an HTML error
# page, or with nothing at all. A status code is therefore never sufficient evidence. Each
# asset must clear three independent gates: 2xx, a non-trivial body size, and a body that
# does not sniff as HTML (regardless of the Content-Type the server claims).
#
# SCOPE BOUNDARY — protocol level only, deliberately (PRD #820).
#   In scope here: HTTP status, body size, and body content type for every referenced
#   asset, plus response *shape* for core API paths. All of it runs with curl, cheaply
#   enough to run on a small box in the middle of a release.
#   Out of scope here: computed styling, layout, and interactivity. Those need a real
#   browser, which is too expensive to run on a two-core box mid-release, so they run in
#   CI against the build artifact instead (issue #837). That split is a decision, not a
#   gap — do not pull browser-level assertions into this script.
#   Wiring this harness into a deploy or cutover path is issue #838, not this script.
#
# No deployment-specific assumptions: no hostname, port, framework asset path, service
# name, or filesystem layout is baked in. It runs against local dev, a candidate
# instance, or current production, identically.
#
# Usage:
#   ./infra/scripts/verify-release-assets.sh --base-url https://example.test
#   ./infra/scripts/verify-release-assets.sh --base-url http://127.0.0.1:3000 \
#       --route / --route /decisions
#   ./infra/scripts/verify-release-assets.sh --base-url https://app.example \
#       --api-base-url https://api.example --api-check /v1/health:status,version
#
# Exit status: 0 when every check passes; non-zero when any fails, with each failing
# asset or API URL named individually in the output.
#
# Note on `set`: -e is deliberately omitted. This is a checker — it must probe every asset
# and report all failures, rather than abort on the first non-2xx. Every command that can
# fail is checked explicitly and failures are accumulated in FAILURES.
set -uo pipefail

BASE_URL=""
API_BASE_URL=""
ROUTES=()
API_CHECKS=()
MIN_ASSET_BYTES=100
TIMEOUT=15

pass_count=0
fail_count=0
FAILURES=()

ok() {
    printf 'PASS: %s\n' "$1"
    pass_count=$((pass_count + 1))
}

bad() {
    printf 'FAIL: %s\n' "$1" >&2
    fail_count=$((fail_count + 1))
    FAILURES+=("$1")
}

usage() {
    cat <<'USAGE'
Usage: verify-release-assets.sh --base-url URL [options]

Fetches each HTML route, discovers every referenced stylesheet and script, fetches each
one, and fails if any is missing, empty, or serves an HTML error body in place of real
content. Status code alone is never treated as sufficient.

Options:
  --base-url URL          Base URL for HTML routes (e.g. http://127.0.0.1:3000).
                          Required unless only --api-check work is requested.
  --route PATH            HTML route to verify. Repeatable. Default: /
  --api-base-url URL      Base URL for API checks. Defaults to --base-url.
  --api-check SPEC        SPEC is PATH[:key1,key2,...]. Asserts 2xx, a valid JSON object
                          body, and the presence of each named top-level key —
                          response shape, not only status. Repeatable.
  --min-asset-bytes N     Minimum body size for a referenced asset (default: 100).
  --timeout SECS          Per-request timeout in seconds (default: 15).
  -h, --help              Show this help and exit 0.

Browser-level computed-styling and interactivity checks are out of scope by design; they
run in CI against the build artifact (issue #837).
USAGE
}

die() {
    printf 'error: %s\n\n' "$1" >&2
    usage >&2
    exit 2
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --base-url)        [ "$#" -ge 2 ] || die "--base-url needs a value"; BASE_URL="$2"; shift 2 ;;
        --api-base-url)    [ "$#" -ge 2 ] || die "--api-base-url needs a value"; API_BASE_URL="$2"; shift 2 ;;
        --route)           [ "$#" -ge 2 ] || die "--route needs a value"; ROUTES+=("$2"); shift 2 ;;
        --api-check)       [ "$#" -ge 2 ] || die "--api-check needs a value"; API_CHECKS+=("$2"); shift 2 ;;
        --min-asset-bytes) [ "$#" -ge 2 ] || die "--min-asset-bytes needs a value"; MIN_ASSET_BYTES="$2"; shift 2 ;;
        --timeout)         [ "$#" -ge 2 ] || die "--timeout needs a value"; TIMEOUT="$2"; shift 2 ;;
        -h|--help)         usage; exit 0 ;;
        *)                 die "unknown argument: $1" ;;
    esac
done

if [ -z "${BASE_URL}" ] && [ -z "${API_BASE_URL}" ]; then
    die "--base-url is required (or --api-base-url when running API checks only)"
fi
[ -n "${API_BASE_URL}" ] || API_BASE_URL="${BASE_URL}"
if [ -n "${BASE_URL}" ] && [ "${#ROUTES[@]}" -eq 0 ]; then
    ROUTES=("/")
fi

BASE_URL="${BASE_URL%/}"
API_BASE_URL="${API_BASE_URL%/}"

command -v curl >/dev/null 2>&1 || die "curl is required"
if [ "${#API_CHECKS[@]}" -gt 0 ]; then
    command -v python3 >/dev/null 2>&1 || die "python3 is required for --api-check JSON shape assertions"
fi

WORK_DIR="$(mktemp -d)" || die "could not create a temp directory"
cleanup() { rm -rf "${WORK_DIR}"; }
trap cleanup EXIT

# ---------------------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------------------

# Fetch $1 into file $2. Emits "code|bytes|content_type" on stdout. Never fails the
# script: a connection error surfaces as code 000, which the callers treat as a failure.
fetch() {
    local url="$1" out="$2" meta=""
    meta="$(curl -sS -m "${TIMEOUT}" -o "${out}" \
        -w '%{http_code}|%{size_download}|%{content_type}' "${url}" 2>/dev/null)"
    if [ -z "${meta}" ]; then
        printf '000|0|\n'
    else
        printf '%s\n' "${meta}"
    fi
}

is_2xx() {
    case "$1" in
        2??) return 0 ;;
        *)   return 1 ;;
    esac
}

# True when the file's leading bytes look like an HTML/XML document. Anchored at the start
# so that a minified bundle merely *containing* "<html" in a string is not misjudged.
body_sniffs_as_html() {
    head -c 512 "$1" 2>/dev/null \
        | tr '[:upper:]' '[:lower:]' \
        | tr -d '[:space:]' \
        | grep -qE '^(<!doctype|<html|<\?xml)'
}

content_type_is_html() {
    case "$1" in
        text/html*|application/xhtml*) return 0 ;;
        *)                             return 1 ;;
    esac
}

# ---------------------------------------------------------------------------------------
# Asset discovery
# ---------------------------------------------------------------------------------------

# Extract href/src values from an HTML file whose path (ignoring any query string or
# fragment) ends in .css or .js. Framework-agnostic on purpose: it reads what the document
# actually references rather than assuming a build tool's static directory.
discover_assets() {
    local html_file="$1"
    grep -oE '(href|src)[[:space:]]*=[[:space:]]*("[^"]*"|'"'"'[^'"'"']*'"'"'|[^"'"'"'[:space:]>]+)' \
        "${html_file}" 2>/dev/null \
        | sed -E 's/^(href|src)[[:space:]]*=[[:space:]]*//' \
        | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/' \
        | grep -E '^[^?#]+\.(css|js)([?#]|$)' \
        | sort -u
}

# Resolve a possibly-relative reference against the origin and the route it was found on.
resolve_url() {
    local ref="$1" origin="$2" route="$3" scheme route_dir
    case "${ref}" in
        http://*|https://*) printf '%s\n' "${ref}"; return ;;
        //*)
            scheme="${origin%%:*}"
            printf '%s:%s\n' "${scheme}" "${ref}"
            return
            ;;
        /*) printf '%s%s\n' "${origin}" "${ref}"; return ;;
    esac
    route_dir="${route%/*}"
    printf '%s%s/%s\n' "${origin}" "${route_dir}" "${ref}"
}

# ---------------------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------------------

# One asset: 2xx, non-trivial body, and a body that is not an HTML document.
check_asset() {
    local url="$1" body meta code bytes ctype
    body="${WORK_DIR}/asset.$$"
    meta="$(fetch "${url}" "${body}")"
    IFS='|' read -r code bytes ctype <<<"${meta}"

    if ! is_2xx "${code}"; then
        bad "asset ${url} returned HTTP ${code}"
        return 1
    fi
    if [ "${bytes:-0}" -lt "${MIN_ASSET_BYTES}" ]; then
        bad "asset ${url} returned HTTP ${code} with a trivial ${bytes}-byte body (minimum ${MIN_ASSET_BYTES}) — a 2xx with no real content is still a broken release"
        return 1
    fi
    if content_type_is_html "${ctype}" || body_sniffs_as_html "${body}"; then
        bad "asset ${url} returned HTTP ${code} carrying an HTML document (content-type '${ctype}', ${bytes} bytes) instead of CSS/JS — an error page served in place of an asset"
        return 1
    fi
    ok "asset ${url} — HTTP ${code}, ${bytes} bytes, ${ctype}"
    return 0
}

check_route() {
    local route="$1" html meta code bytes ctype url asset_count=0 route_failures=0
    case "${route}" in
        /*) ;;
        *)  route="/${route}" ;;
    esac
    local page_url="${BASE_URL}${route}"
    html="${WORK_DIR}/page.$$"
    meta="$(fetch "${page_url}" "${html}")"
    IFS='|' read -r code bytes ctype <<<"${meta}"

    if ! is_2xx "${code}"; then
        bad "route ${page_url} returned HTTP ${code}"
        return 1
    fi
    if [ "${bytes:-0}" -eq 0 ]; then
        bad "route ${page_url} returned HTTP ${code} with an empty body"
        return 1
    fi
    ok "route ${page_url} — HTTP ${code}, ${bytes} bytes"

    while IFS= read -r ref; do
        [ -n "${ref}" ] || continue
        asset_count=$((asset_count + 1))
        url="$(resolve_url "${ref}" "${BASE_URL}" "${route}")"
        check_asset "${url}" || route_failures=$((route_failures + 1))
    done < <(discover_assets "${html}")

    if [ "${asset_count}" -eq 0 ]; then
        bad "route ${page_url} referenced no stylesheets or scripts at all — a rendered page with zero CSS/JS is the missing-build symptom, not a healthy page"
        return 1
    fi
    if [ "${route_failures}" -gt 0 ]; then
        return 1
    fi
    ok "route ${page_url} — all ${asset_count} referenced assets served real content"
    return 0
}

# One API path: 2xx plus a JSON object carrying each required top-level key. Shape, not
# only status — a healthy process with a broken route answers 200 with the wrong body.
json_shape_error() {
    local file="$1" keys="$2"
    python3 - "${file}" "${keys}" <<'PY'
import json
import sys

path, keys = sys.argv[1], sys.argv[2]
try:
    with open(path, "rb") as handle:
        document = json.load(handle)
except Exception as exc:  # noqa: BLE001 - any parse failure is a shape failure
    print(f"body is not valid JSON ({exc})")
    raise SystemExit(1)
if not isinstance(document, dict):
    print(f"expected a JSON object, got {type(document).__name__}")
    raise SystemExit(1)
missing = [key for key in (k.strip() for k in keys.split(",")) if key and key not in document]
if missing:
    print("response is missing required field(s): " + ", ".join(missing))
    raise SystemExit(1)
PY
}

check_api() {
    local spec="$1" path keys body meta code bytes ctype detail
    path="${spec%%:*}"
    if [ "${path}" = "${spec}" ]; then
        keys=""
    else
        keys="${spec#*:}"
    fi
    case "${path}" in
        /*) ;;
        *)  path="/${path}" ;;
    esac
    local url="${API_BASE_URL}${path}"
    body="${WORK_DIR}/api.$$"
    meta="$(fetch "${url}" "${body}")"
    IFS='|' read -r code bytes ctype <<<"${meta}"

    if ! is_2xx "${code}"; then
        bad "api ${url} returned HTTP ${code}"
        return 1
    fi
    if content_type_is_html "${ctype}" || body_sniffs_as_html "${body}"; then
        bad "api ${url} returned HTTP ${code} carrying an HTML document (content-type '${ctype}') instead of JSON"
        return 1
    fi
    detail="$(json_shape_error "${body}" "${keys}")"
    if [ -n "${detail}" ]; then
        bad "api ${url} returned HTTP ${code} but ${detail}"
        return 1
    fi
    if [ -n "${keys}" ]; then
        ok "api ${url} — HTTP ${code}, JSON object with ${keys}"
    else
        ok "api ${url} — HTTP ${code}, valid JSON object"
    fi
    return 0
}

# ---------------------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------------------

echo "== release asset verification =="
[ -n "${BASE_URL}" ] && echo "page base : ${BASE_URL}"
[ "${#API_CHECKS[@]}" -gt 0 ] && echo "api base  : ${API_BASE_URL}"
echo "min asset bytes: ${MIN_ASSET_BYTES}   timeout: ${TIMEOUT}s"
echo

for route in "${ROUTES[@]+"${ROUTES[@]}"}"; do
    check_route "${route}"
    echo
done

for spec in "${API_CHECKS[@]+"${API_CHECKS[@]}"}"; do
    check_api "${spec}"
done

echo
echo "== summary: ${pass_count} passed, ${fail_count} failed =="
if [ "${fail_count}" -gt 0 ]; then
    echo "failing checks:" >&2
    for failure in "${FAILURES[@]}"; do
        printf '  - %s\n' "${failure}" >&2
    done
    exit 1
fi
echo "All referenced assets and API paths served real content."
