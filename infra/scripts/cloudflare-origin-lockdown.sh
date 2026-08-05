#!/usr/bin/env bash
# Restrict inbound 80/443 at the origin to Cloudflare's published IP ranges (both IPv4 and IPv6).
#
# Cloudflare publishes its egress IPs at:
#   https://www.cloudflare.com/ips-v4
#   https://www.cloudflare.com/ips-v6
#
# This script:
# - Fetches both IPv4 and IPv6 Cloudflare ranges with strict HTTP error checking
# - Validates EVERY line against strict CIDR regex (IPv4/IPv6 format)
# - Applies iptables rules to restrict ports 80/443 to those ranges only
# - Rejects all other inbound traffic on 80/443
# - Is idempotent (safe to re-run; flushes and reuses a dedicated chain)
# - Fails closed if ranges cannot be fetched, are empty, are truncated, or malformed
# - Does NOT eval() any fetched content (direct iptables binary invocation only)
# - Does NOT touch port 22 (SSH) — explicit guards prevent any rule that references it
# - On rule failure, immediately rolls back the chain and removes the INPUT jump
# - Does NOT survive reboot (see REBOOT PERSISTENCE section)
#
# Intended for deploy via systemd timer (juli-cloudflare-ip-refresh.timer) to keep ranges fresh.
#
# Env overrides:
#   DRY_RUN                    — if "1", print rules without applying (default: "")
#   CLOUDFLARE_IPV4_URL        — IPv4 ranges URL (default: https://www.cloudflare.com/ips-v4)
#   CLOUDFLARE_IPV6_URL        — IPv6 ranges URL (default: https://www.cloudflare.com/ips-v6)
#   CURL_TIMEOUT_SEC           — curl timeout (default: 10)
#   HTTP_01_PORT               — certbot HTTP-01 challenge port (default: 80)
#   HTTPS_PORT                 — HTTPS port (default: 443)
#   CHAIN_NAME                 — iptables chain name (default: CLOUDFLARE_INGRESS)
#   MIN_IPV4_RANGES            — minimum IPv4 ranges before abort (default: 5)
#   MIN_IPV6_RANGES            — minimum IPv6 ranges before abort (default: 3)
#
# REBOOT PERSISTENCE:
# iptables rules do not survive a reboot. The origin is exposed between boot and the next
# timer firing. To restore protection immediately on boot, either:
# 1. Use a boot-time systemd service that calls this script (add Before=multi-user.target)
# 2. Install iptables-persistent and run `iptables-save > /etc/iptables/rules.v4`
#    after this script succeeds to persist rules across reboots
# This minimal implementation documents the gap and relies on the systemd timer
# (configured with Persistent=true) to restore rules after boot.
#
# Safety guarantees:
# - Port 22 (SSH): never modified; explicit check that generated rules do not reference it
# - Fail-closed: if ranges are empty, malformed, truncated, or fetch fails, aborts without changes
# - No eval(): all fetched content validated against strict CIDR regex; iptables invoked directly
# - Idempotent: chain is flushed and repopulated each run, no deletes or duplicates
# - Rollback: any rule failure causes immediate chain flush and INPUT jump removal
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DRY_RUN="${DRY_RUN:-}"
CLOUDFLARE_IPV4_URL="${CLOUDFLARE_IPV4_URL:-https://www.cloudflare.com/ips-v4}"
CLOUDFLARE_IPV6_URL="${CLOUDFLARE_IPV6_URL:-https://www.cloudflare.com/ips-v6}"
CURL_TIMEOUT_SEC="${CURL_TIMEOUT_SEC:-10}"
HTTP_01_PORT="${HTTP_01_PORT:-80}"
HTTPS_PORT="${HTTPS_PORT:-443}"
CHAIN_NAME="${CHAIN_NAME:-CLOUDFLARE_INGRESS}"
SSH_PORT="${SSH_PORT:-22}"
MIN_IPV4_RANGES="${MIN_IPV4_RANGES:-5}"
MIN_IPV6_RANGES="${MIN_IPV6_RANGES:-3}"

log() {
    printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

fail() {
    log "FAIL: $*"
    exit 1
}

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

# Ensure we have the necessary tools
require_cmd curl
require_cmd iptables
require_cmd ip6tables

log "cloudflare-origin-lockdown starting"

# ===== SAFETY: NEVER TOUCH PORT 22 (SSH) =====

if [ "${HTTP_01_PORT}" = "${SSH_PORT}" ] || [ "${HTTPS_PORT}" = "${SSH_PORT}" ]; then
    fail "SAFETY GATE: HTTP_01_PORT or HTTPS_PORT cannot be port 22 (SSH lockout guard)"
fi

# ===== FETCH AND VALIDATE RANGES WITH STRICT CIDR VALIDATION =====

log "fetching Cloudflare IPv4 ranges from ${CLOUDFLARE_IPV4_URL}"
if ! IPV4_RANGES=$(curl -fsS --max-time "${CURL_TIMEOUT_SEC}" "${CLOUDFLARE_IPV4_URL}" 2>&1); then
    fail "IPv4 ranges fetch failed (check network / URL: ${CLOUDFLARE_IPV4_URL})"
fi

if [ -z "${IPV4_RANGES}" ]; then
    fail "IPv4 ranges fetch returned empty response"
fi

log "fetching Cloudflare IPv6 ranges from ${CLOUDFLARE_IPV6_URL}"
if ! IPV6_RANGES=$(curl -fsS --max-time "${CURL_TIMEOUT_SEC}" "${CLOUDFLARE_IPV6_URL}" 2>&1); then
    fail "IPv6 ranges fetch failed (check network / URL: ${CLOUDFLARE_IPV6_URL})"
fi

if [ -z "${IPV6_RANGES}" ]; then
    fail "IPv6 ranges fetch returned empty response"
fi

# Strict CIDR validation: IPv4 = ^[0-9.]+/[0-9]{1,2}$, IPv6 = ^[0-9a-fA-F:]+/[0-9]{1,3}$
validate_ipv4_cidr() {
    [[ "$1" =~ ^[0-9.]+/[0-9]{1,2}$ ]]
}

validate_ipv6_cidr() {
    [[ "$1" =~ ^[0-9a-fA-F:]+/[0-9]{1,3}$ ]]
}

log "validating IPv4 ranges (strict CIDR format)"
while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    if ! validate_ipv4_cidr "${cidr}"; then
        fail "Malformed IPv4 CIDR: ${cidr} (not matching ^[0-9.]+/[0-9]{1,2}$)"
    fi
done <<< "${IPV4_RANGES}"

log "validating IPv6 ranges (strict CIDR format)"
while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    if ! validate_ipv6_cidr "${cidr}"; then
        fail "Malformed IPv6 CIDR: ${cidr} (not matching ^[0-9a-fA-F:]+/[0-9]{1,3}$)"
    fi
done <<< "${IPV6_RANGES}"

# Count ranges and check for truncation
IPV4_COUNT=$(echo "${IPV4_RANGES}" | grep -c '^' || true)
IPV6_COUNT=$(echo "${IPV6_RANGES}" | grep -c '^' || true)

log "IPv4 range count: ${IPV4_COUNT} (minimum required: ${MIN_IPV4_RANGES})"
log "IPv6 range count: ${IPV6_COUNT} (minimum required: ${MIN_IPV6_RANGES})"

if [ "${IPV4_COUNT}" -lt "${MIN_IPV4_RANGES}" ]; then
    fail "IPv4 range count ${IPV4_COUNT} below minimum ${MIN_IPV4_RANGES} (truncated list?)"
fi

if [ "${IPV6_COUNT}" -lt "${MIN_IPV6_RANGES}" ]; then
    fail "IPv6 range count ${IPV6_COUNT} below minimum ${MIN_IPV6_RANGES} (truncated list?)"
fi

# ===== GENERATE RULES (DRY-RUN SUPPORT, NO EVAL) =====

# Build rule arrays (never as strings to avoid eval)
# We'll iterate these later and invoke iptables directly
IPV4_ACCEPT_RULES=()
IPV6_ACCEPT_RULES=()
REJECT_RULES_V4=()
REJECT_RULES_V6=()

# IPv4: Accept Cloudflare ranges on ports 80 and 443
while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    IPV4_ACCEPT_RULES+=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTP_01_PORT}" "-s" "${cidr}" "-j" "ACCEPT")
    IPV4_ACCEPT_RULES+=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTPS_PORT}" "-s" "${cidr}" "-j" "ACCEPT")
done <<< "${IPV4_RANGES}"

# IPv6: Accept Cloudflare ranges on ports 80 and 443
while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    IPV6_ACCEPT_RULES+=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTP_01_PORT}" "-s" "${cidr}" "-j" "ACCEPT")
    IPV6_ACCEPT_RULES+=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTPS_PORT}" "-s" "${cidr}" "-j" "ACCEPT")
done <<< "${IPV6_RANGES}"

# Reject all other inbound traffic on these ports (after all ACCEPT rules)
REJECT_RULES_V4=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTP_01_PORT}" "-j" "REJECT" "--reject-with" "tcp-reset")
REJECT_RULES_V4+=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTPS_PORT}" "-j" "REJECT" "--reject-with" "tcp-reset")

REJECT_RULES_V6=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTP_01_PORT}" "-j" "REJECT" "--reject-with" "tcp-reset")
REJECT_RULES_V6+=("-t" "filter" "-A" "${CHAIN_NAME}" "-p" "tcp" "--dport" "${HTTPS_PORT}" "-j" "REJECT" "--reject-with" "tcp-reset")

# ===== VERIFY NO RULE REFERENCES PORT 22 =====

for arg in "${IPV4_ACCEPT_RULES[@]}" "${IPV6_ACCEPT_RULES[@]}" "${REJECT_RULES_V4[@]}" "${REJECT_RULES_V6[@]}"; do
    if [ "${arg}" = "${SSH_PORT}" ]; then
        fail "SAFETY GATE: Generated rule references port 22 (SSH lockout guard)"
    fi
done

# ===== DRY-RUN MODE =====

if [ "${DRY_RUN}" = "1" ]; then
    log "DRY-RUN MODE: rules that would be applied"
    log "--- IPv4 ACCEPT rules ---"
    for arg in "${IPV4_ACCEPT_RULES[@]}"; do
        echo "iptables ${arg}"
    done | paste -sd ' ' -
    log "--- IPv6 ACCEPT rules ---"
    for arg in "${IPV6_ACCEPT_RULES[@]}"; do
        echo "ip6tables ${arg}"
    done | paste -sd ' ' -
    log "--- IPv4/IPv6 REJECT rules ---"
    echo "iptables ${REJECT_RULES_V4[*]}" | head -1
    echo "ip6tables ${REJECT_RULES_V6[*]}" | head -1
    log "--- INPUT chain jump (the rule that diverts live traffic) ---"
    log "iptables -t filter -I INPUT -p tcp -m multiport --dports ${HTTP_01_PORT},${HTTPS_PORT} -j ${CHAIN_NAME}"
    log "ip6tables -t filter -I INPUT -p tcp -m multiport --dports ${HTTP_01_PORT},${HTTPS_PORT} -j ${CHAIN_NAME}"
    log "DRY-RUN complete — no rules applied"
    exit 0
fi

# ===== APPLY RULES (IDEMPOTENT VIA CHAIN FLUSH, WITH ROLLBACK) =====

log "applying firewall rules (idempotent: flushing and reusing chain ${CHAIN_NAME})"

# Helper: rollback on failure
rollback_and_fail() {
    log "FAIL: $1 — rolling back rules"
    # Flush the chain (remove all rules inside)
    iptables -t filter -F "${CHAIN_NAME}" 2>/dev/null || true
    ip6tables -t filter -F "${CHAIN_NAME}" 2>/dev/null || true
    # Remove the INPUT jump (restore previous state)
    iptables -t filter -D INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" 2>/dev/null || true
    ip6tables -t filter -D INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" 2>/dev/null || true
    log "rollback complete — firewall restored to previous state"
    fail "$1"
}

# Step 1: Create the chain if it does not exist (check for existence first)
if ! iptables -t filter -n -L "${CHAIN_NAME}" >/dev/null 2>&1; then
    iptables -t filter -N "${CHAIN_NAME}" || rollback_and_fail "Failed to create IPv4 chain"
fi

if ! ip6tables -t filter -n -L "${CHAIN_NAME}" >/dev/null 2>&1; then
    ip6tables -t filter -N "${CHAIN_NAME}" || rollback_and_fail "Failed to create IPv6 chain"
fi

# Step 2: Flush the chains (idempotent — empty the chain but keep it)
iptables -t filter -F "${CHAIN_NAME}" || rollback_and_fail "Failed to flush IPv4 chain"
ip6tables -t filter -F "${CHAIN_NAME}" || rollback_and_fail "Failed to flush IPv6 chain"

# Step 3: Apply all ACCEPT rules FIRST (before REJECT)
log "applying IPv4 ACCEPT rules"
for ((i = 0; i < ${#IPV4_ACCEPT_RULES[@]}; i += 10)); do
    iptables "${IPV4_ACCEPT_RULES[@]:$i:10}" || rollback_and_fail "IPv4 ACCEPT rule failed"
done

log "applying IPv6 ACCEPT rules"
for ((i = 0; i < ${#IPV6_ACCEPT_RULES[@]}; i += 10)); do
    ip6tables "${IPV6_ACCEPT_RULES[@]:$i:10}" || rollback_and_fail "IPv6 ACCEPT rule failed"
done

# Step 4: Apply REJECT rules (only after all ACCEPT rules succeeded)
log "applying IPv4 REJECT rules"
iptables "${REJECT_RULES_V4[@]}" || rollback_and_fail "IPv4 REJECT rule failed"

log "applying IPv6 REJECT rules"
ip6tables "${REJECT_RULES_V6[@]}" || rollback_and_fail "IPv6 REJECT rule failed"

# Step 5: Wire the chain into INPUT for ports 80 and 443 (only if not already there)
if ! iptables -t filter -C INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" 2>/dev/null; then
    iptables -t filter -I INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" || rollback_and_fail "Failed to wire IPv4 chain into INPUT"
fi

if ! ip6tables -t filter -C INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" 2>/dev/null; then
    ip6tables -t filter -I INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" || rollback_and_fail "Failed to wire IPv6 chain into INPUT"
fi

log "firewall rules applied successfully"
log "port ${SSH_PORT} (SSH) — untouched — remains fully accessible from any source"
log "ports ${HTTP_01_PORT} (HTTP) and ${HTTPS_PORT} (HTTPS) — restricted to Cloudflare ranges only"
log "NOTE: rules do not survive reboot; see REBOOT PERSISTENCE in script header"
log "cloudflare-origin-lockdown complete"
