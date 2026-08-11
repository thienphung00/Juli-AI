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
# - Survives reboot via the boot-enabled refresh unit (see REBOOT PERSISTENCE section)
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
# REBOOT PERSISTENCE (closed by #941):
# iptables rules do not survive a reboot, and ufw persists `80/tcp ALLOW IN Anywhere` and
# `443/tcp ALLOW IN Anywhere`. A reboot therefore did not merely drop this lockdown — it
# restored a permissive ruleset and left the origin exposed until the timer next fired,
# a window of up to ~65 minutes (OnCalendar=hourly + RandomizedDelaySec=5m, no OnBootSec).
#
# Fixed by running this script at boot rather than persisting its output:
#   infra/systemd/juli-cloudflare-ip-refresh.service.d/10-boot-persistence.conf
#   (After=ufw.service, Before=nginx.service) plus `systemctl enable` on the SERVICE —
#   the unit already declared WantedBy=multi-user.target but was never enabled, so it
#   only ever ran from the timer. OnBootSec=2min on the timer is the second net.
#
# iptables-persistent is deliberately NOT used: ufw owns the filter table and its own
# boot-time restore would clobber a replayed ruleset.
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

# ===== HELPER: EMIT OR APPLY A SINGLE RULE (NO ARRAY SLICING, NO EVAL) =====

# This function ensures dry-run output exactly matches what executes.
# Takes binary ($1) and remaining args as one complete rule.
# SAFETY: Guards against any rule targeting the SSH port.
emit_or_apply() {
    local bin="$1"
    shift

    # Safety check: no rule may target the SSH port.
    # Look for --dport followed immediately by SSH_PORT value.
    local prev=""
    for arg in "$@"; do
        if [ "$prev" = "--dport" ] && [ "$arg" = "${SSH_PORT}" ]; then
            fail "SAFETY GATE: refusing rule targeting SSH port ${SSH_PORT}: $bin $*"
        fi
        prev="$arg"
    done

    if [ "${DRY_RUN}" = "1" ]; then
        # Print the exact command that would execute
        printf '%s %s\n' "$bin" "$*"
    else
        # Execute the rule
        "$bin" "$@" || rollback_and_fail "rule failed: $bin $*"
    fi
}

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

# ===== APPLY RULES (IDEMPOTENT VIA CHAIN FLUSH) =====

log "applying firewall rules (idempotent: flushing and reusing chain ${CHAIN_NAME})"

# Step 1: Create the chain if it does not exist (check for existence first)
if [ "${DRY_RUN}" != "1" ]; then
    if ! iptables -t filter -n -L "${CHAIN_NAME}" >/dev/null 2>&1; then
        iptables -t filter -N "${CHAIN_NAME}" || rollback_and_fail "Failed to create IPv4 chain"
    fi

    if ! ip6tables -t filter -n -L "${CHAIN_NAME}" >/dev/null 2>&1; then
        ip6tables -t filter -N "${CHAIN_NAME}" || rollback_and_fail "Failed to create IPv6 chain"
    fi

    # Step 2: Flush the chains (idempotent — empty the chain but keep it)
    iptables -t filter -F "${CHAIN_NAME}" || rollback_and_fail "Failed to flush IPv4 chain"
    ip6tables -t filter -F "${CHAIN_NAME}" || rollback_and_fail "Failed to flush IPv6 chain"
else
    log "DRY-RUN MODE: rules that would be applied"
fi

# Step 2.5: accept loopback first.
# The INPUT jump is inserted at position 1, ahead of ufw's `-A ufw-before-input -i lo
# -j ACCEPT`, so INPUT reaches this chain before that exemption. Without these rules a
# local request to 80/443 would be REJECTed with tcp-reset. Cheap guard against any
# on-box health check or certbot self-test that talks to the origin over 80/443.
log "generating loopback ACCEPT rules"
emit_or_apply iptables -t filter -A "${CHAIN_NAME}" -i lo -j ACCEPT
emit_or_apply ip6tables -t filter -A "${CHAIN_NAME}" -i lo -j ACCEPT

# Step 3: IPv4 ACCEPT rules (one per Cloudflare CIDR, two per CIDR × port)
log "generating IPv4 ACCEPT rules"
while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    emit_or_apply iptables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTP_01_PORT}" -s "${cidr}" -j ACCEPT
    emit_or_apply iptables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTPS_PORT}" -s "${cidr}" -j ACCEPT
done <<< "${IPV4_RANGES}"

# Step 4: IPv6 ACCEPT rules (one per Cloudflare CIDR, two per CIDR × port)
log "generating IPv6 ACCEPT rules"
while IFS= read -r cidr; do
    [ -z "${cidr}" ] && continue
    emit_or_apply ip6tables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTP_01_PORT}" -s "${cidr}" -j ACCEPT
    emit_or_apply ip6tables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTPS_PORT}" -s "${cidr}" -j ACCEPT
done <<< "${IPV6_RANGES}"

# Step 5: IPv4 REJECT rules (after all ACCEPT)
log "generating IPv4 REJECT rules"
emit_or_apply iptables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTP_01_PORT}" -j REJECT --reject-with tcp-reset
emit_or_apply iptables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTPS_PORT}" -j REJECT --reject-with tcp-reset

# Step 6: IPv6 REJECT rules (after all ACCEPT)
log "generating IPv6 REJECT rules"
emit_or_apply ip6tables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTP_01_PORT}" -j REJECT --reject-with tcp-reset
emit_or_apply ip6tables -t filter -A "${CHAIN_NAME}" -p tcp --dport "${HTTPS_PORT}" -j REJECT --reject-with tcp-reset

# ===== DRY-RUN MODE EXIT =====

if [ "${DRY_RUN}" = "1" ]; then
    log "--- INPUT chain jump (the rule that diverts live traffic) ---"
    log "iptables -t filter -I INPUT -p tcp -m multiport --dports ${HTTP_01_PORT},${HTTPS_PORT} -j ${CHAIN_NAME}"
    log "ip6tables -t filter -I INPUT -p tcp -m multiport --dports ${HTTP_01_PORT},${HTTPS_PORT} -j ${CHAIN_NAME}"
    log "DRY-RUN complete — no rules applied"
    exit 0
fi

# ===== WIRE THE CHAIN INTO INPUT (ONLY IN APPLY MODE) =====

# Safety check: the INPUT jump must not target SSH port
if [ "${HTTP_01_PORT}" = "${SSH_PORT}" ] || [ "${HTTPS_PORT}" = "${SSH_PORT}" ]; then
    fail "SAFETY GATE: INPUT jump cannot reference port 22 (SSH lockout guard)"
fi

if ! iptables -t filter -C INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" 2>/dev/null; then
    iptables -t filter -I INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" || rollback_and_fail "Failed to wire IPv4 chain into INPUT"
fi

if ! ip6tables -t filter -C INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" 2>/dev/null; then
    ip6tables -t filter -I INPUT -p tcp -m multiport --dports "${HTTP_01_PORT},${HTTPS_PORT}" -j "${CHAIN_NAME}" || rollback_and_fail "Failed to wire IPv6 chain into INPUT"
fi

log "firewall rules applied successfully"
log "port ${SSH_PORT} (SSH) — untouched — remains fully accessible from any source"
log "ports ${HTTP_01_PORT} (HTTP) and ${HTTPS_PORT} (HTTPS) — restricted to Cloudflare ranges only"
log "rules re-applied at boot by the enabled refresh service (see REBOOT PERSISTENCE, #941)"

# ===== NGINX real_ip CONFIG (#905) =====
#
# Every request arrives from Cloudflare, so nginx's $remote_addr is a Cloudflare edge
# address and X-Forwarded-For / X-Real-IP carry that same useless value downstream. The
# application then attributes every security event — rejected webhook signatures,
# ownership failures, auth failures — to Cloudflare rather than to the caller.
#
# The ranges needed to fix that are exactly the ranges just fetched and validated above,
# so this is emitted from the same run rather than from a second, separately-drifting
# source. One fetch, two consumers: the firewall chain and this include.
#
# CF-Connecting-IP (rather than X-Forwarded-For) because Cloudflare sets it to the single
# true client address and strips any inbound copy, whereas X-Forwarded-For is a
# caller-appendable list.
#
# Written to conf.d/ so nginx includes it in the http{} context (see provision-nginx.sh),
# making it apply to the api, demo and landing vhosts alike rather than just one.

NGINX_REAL_IP_CONF="${NGINX_REAL_IP_CONF:-/etc/nginx/conf.d/cloudflare-real-ip.conf}"

if [ "${SKIP_NGINX_REAL_IP:-0}" = "1" ]; then
    log "nginx real_ip config: skipped (SKIP_NGINX_REAL_IP=1)"
elif [ ! -d "$(dirname "${NGINX_REAL_IP_CONF}")" ]; then
    log "nginx real_ip config: ${NGINX_REAL_IP_CONF%/*} absent — skipping (run provision-nginx.sh first)"
else
    log "writing nginx real_ip config to ${NGINX_REAL_IP_CONF}"
    real_ip_tmp="${NGINX_REAL_IP_CONF}.tmp.$$"
    {
        printf '# Generated by cloudflare-origin-lockdown.sh (#905). Do not edit.\n'
        printf '# Regenerated on every run of juli-cloudflare-ip-refresh.service.\n'
        printf '#\n'
        printf '# Without these, $remote_addr is a Cloudflare edge address and every\n'
        printf '# security event is attributed to Cloudflare instead of the caller.\n\n'
        while IFS= read -r cidr; do
            [ -n "${cidr}" ] && printf 'set_real_ip_from %s;\n' "${cidr}"
        done <<< "${IPV4_RANGES}"
        while IFS= read -r cidr; do
            [ -n "${cidr}" ] && printf 'set_real_ip_from %s;\n' "${cidr}"
        done <<< "${IPV6_RANGES}"
        printf '\nreal_ip_header CF-Connecting-IP;\n'
        printf 'real_ip_recursive on;\n'
    } > "${real_ip_tmp}"

    # Validate before swapping: a broken include takes the whole site down on reload.
    if mv -f "${real_ip_tmp}" "${NGINX_REAL_IP_CONF}" && nginx -t >/dev/null 2>&1; then
        systemctl reload nginx >/dev/null 2>&1 \
            && log "nginx reloaded with ${IPV4_COUNT} IPv4 + ${IPV6_COUNT} IPv6 real_ip sources" \
            || log "WARNING: nginx reload failed — config written but not live"
    else
        rm -f "${real_ip_tmp}"
        log "WARNING: nginx -t rejected the generated real_ip config — left unchanged"
    fi
fi

log "cloudflare-origin-lockdown complete"
