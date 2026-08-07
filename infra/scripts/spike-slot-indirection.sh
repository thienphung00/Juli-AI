#!/usr/bin/env bash
# Spike (issue #835): prove slot-based release indirection starts correctly on the VPS.
#
# The paired-slot design in PRD #820 runs every deployable from a *slot* symlink
# (~/releases/demo-slot-a) that points at an immutable release worktree, rather than
# from the release path directly. The open risk is that Next.js + a pnpm workspace
# whose dependency tree is itself symlinked cannot start through that extra level of
# indirection. That would invalidate the paired-slot approach, not merely complicate
# it — so it is proven here before any slot layout is committed to.
#
# What this proves (or refutes):
#   1. An app starts from a slot indirection and serves a correct page with assets intact.
#   2. Two slots for the same app run concurrently on different ports without interfering.
#   3. Repointing a slot's symlink and restarting picks up the new release (BUILD_ID changes).
#
# SAFETY — this script never touches production:
#   * never writes ~/releases/demo-current, never restarts juli-demo, never binds :3001
#   * never prunes, removes, or rebuilds an existing release worktree
#   * asserts live Demo on :3001 still answers 2xx before, between, and after every step
#   * removes only the slot symlinks and transient units it created
#
# Usage (on the VPS, as root):
#   ./infra/scripts/spike-slot-indirection.sh
#
# Env overrides: SLOT_A_PORT (3011), SLOT_B_PORT (3012), START_TIMEOUT_SECS (90),
#                MIN_FREE_MB (700), KEEP_SLOTS=1 (leave slots + units running for inspection)
set -uo pipefail

RELEASES_ROOT="${RELEASES_ROOT:-$HOME/releases}"
DEMO_CURRENT="${RELEASES_ROOT}/demo-current"
SLOT_A="${RELEASES_ROOT}/demo-slot-a"
SLOT_B="${RELEASES_ROOT}/demo-slot-b"
SLOT_A_PORT="${SLOT_A_PORT:-3011}"
SLOT_B_PORT="${SLOT_B_PORT:-3012}"
LIVE_PORT="3001"
START_TIMEOUT_SECS="${START_TIMEOUT_SECS:-90}"
MIN_FREE_MB="${MIN_FREE_MB:-700}"
UNIT_A="juli-demo-spike-a"
UNIT_B="juli-demo-spike-b"
REPORT="${RELEASES_ROOT}/spike-835-findings.txt"

PASS_COUNT=0
FAIL_COUNT=0
FINDINGS=()

log()  { printf '\n== %s ==\n' "$*"; }
note() { printf '   %s\n' "$*"; FINDINGS+=("$*"); }
ok()   { printf 'PASS: %s\n' "$*"; PASS_COUNT=$((PASS_COUNT + 1)); FINDINGS+=("PASS: $*"); }
bad()  { printf 'FAIL: %s\n' "$*" >&2; FAIL_COUNT=$((FAIL_COUNT + 1)); FINDINGS+=("FAIL: $*"); }

free_mb() { free -m 2>/dev/null | awk '/^Mem:/{print $7}'; }

http_code() {
    # curl already prints 000 on a connection failure; a `|| echo 000` fallback would
    # concatenate onto it and report "000000", so capture and default instead.
    local code
    code="$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$1" 2>/dev/null)"
    echo "${code:-000}"
}

# Live Demo must be healthy at every checkpoint. If it is not, stop immediately —
# a spike must never be the reason production went down.
assert_live_ok() {
    local where="$1" code
    code="$(http_code "http://127.0.0.1:${LIVE_PORT}/decisions")"
    if [[ "${code}" =~ ^2 ]]; then
        note "live Demo :${LIVE_PORT} still 2xx (${where})"
        return 0
    fi
    bad "live Demo :${LIVE_PORT} returned ${code} at checkpoint '${where}' — aborting spike"
    cleanup
    finish
    exit 1
}

wait_for_port() {
    local url="$1" deadline=$((SECONDS + START_TIMEOUT_SECS)) code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        code="$(http_code "${url}")"
        [[ "${code}" =~ ^2 ]] && { echo "${code}"; return 0; }
        sleep 3
    done
    echo "${code}"
    return 1
}

# Fetch every stylesheet and script the page references and assert each is 2xx with a
# non-trivial body. A slot that serves HTML but 404s its hashed chunks is the exact
# failure this design exists to catch, so the spike must not accept status alone.
verify_assets() {
    local base="$1" html asset code bytes missing=0 checked=0
    html="$(curl -s -m 15 "${base}/decisions" 2>/dev/null)"
    if [ -z "${html}" ]; then
        bad "no HTML body from ${base}/decisions"
        return 1
    fi
    while read -r asset; do
        [ -n "${asset}" ] || continue
        case "${asset}" in
            http*) continue ;;                      # spike scope: same-origin assets only
            /*) ;;
            *) continue ;;
        esac
        checked=$((checked + 1))
        code="$(http_code "${base}${asset}")"
        bytes="$(curl -s -m 15 -o /dev/null -w '%{size_download}' "${base}${asset}" 2>/dev/null || echo 0)"
        if [[ ! "${code}" =~ ^2 ]] || [ "${bytes}" -lt 100 ]; then
            bad "asset ${asset} -> code=${code} bytes=${bytes} (via ${base})"
            missing=$((missing + 1))
        fi
    done < <(printf '%s' "${html}" \
        | grep -oE '(href|src)="[^"]+\.(css|js)"' \
        | sed -E 's/^(href|src)="//; s/"$//' \
        | sort -u)

    if [ "${checked}" -eq 0 ]; then
        bad "page at ${base} referenced no CSS/JS at all — cannot be a healthy Next.js render"
        return 1
    fi
    if [ "${missing}" -eq 0 ]; then
        ok "all ${checked} referenced assets served with real bodies via ${base}"
        return 0
    fi
    return 1
}

build_id() {
    local slot="$1"
    cat "${slot}/apps/demo/.next/BUILD_ID" 2>/dev/null || echo "unknown"
}

# Start a Demo instance through the slot symlink using a transient systemd unit.
# systemd-run mirrors the real juli-demo unit (Type=simple, WorkingDirectory inside the
# slot, the slot-local next binary) so this also proves systemd resolves a symlinked
# WorkingDirectory — using nohup here would prove strictly less than production needs.
start_slot() {
    local unit="$1" slot="$2" port="$3" freemb
    freemb="$(free_mb)"
    if [ -n "${freemb}" ] && [ "${freemb}" -lt "${MIN_FREE_MB}" ]; then
        bad "only ${freemb}MB free — refusing to start ${unit} (need ${MIN_FREE_MB}MB); memory ceiling is a real finding"
        return 1
    fi
    systemctl reset-failed "${unit}" 2>/dev/null || true
    systemd-run --unit="${unit}" --collect \
        --property=Type=simple \
        --property=WorkingDirectory="${slot}/apps/demo" \
        --property=Restart=no \
        "${slot}/apps/demo/node_modules/.bin/next" start --port "${port}" --hostname 127.0.0.1 \
        >/dev/null 2>&1
}

stop_slot() {
    local unit="$1"
    systemctl stop "${unit}" 2>/dev/null || true
    systemctl reset-failed "${unit}" 2>/dev/null || true
}

dump_unit() {
    local unit="$1"
    echo "-- ${unit} status --" >&2
    systemctl --no-pager --full status "${unit}" 2>&1 | head -20 >&2 || true
    echo "-- ${unit} logs --" >&2
    journalctl -u "${unit}" -n 40 --no-pager 2>&1 >&2 || true
}

cleanup() {
    log "cleanup (production untouched)"
    if [ "${KEEP_SLOTS:-0}" = "1" ]; then
        note "KEEP_SLOTS=1 — leaving ${UNIT_A}/${UNIT_B} and slot symlinks in place"
        return
    fi
    stop_slot "${UNIT_A}"
    stop_slot "${UNIT_B}"
    rm -f "${SLOT_A}" "${SLOT_B}"
    note "stopped spike units, removed slot symlinks; no release worktree was modified"
}

finish() {
    log "findings (issue #835)"
    printf '%s\n' "${FINDINGS[@]}" | tee "${REPORT}"
    printf '\nchecks passed: %s   failed: %s\n' "${PASS_COUNT}" "${FAIL_COUNT}" | tee -a "${REPORT}"
    echo "Report written to ${REPORT} — paste it onto issue #835."
}

trap 'cleanup; finish' EXIT

log "spike #835: slot-based release indirection"
echo "releases root : ${RELEASES_ROOT}"
echo "live demo     : $(readlink -f "${DEMO_CURRENT}" 2>/dev/null || echo MISSING)"
echo "free memory   : $(free_mb)MB"
note "free memory at start: $(free_mb)MB"

assert_live_ok "before the spike"

# --- Pick two distinct, already-built releases. Never build, never prune. ---
log "selecting release worktrees (read-only)"
mapfile -t BUILT < <(find "${RELEASES_ROOT}" -maxdepth 1 -mindepth 1 -type d \
    -exec test -f '{}/apps/demo/.next/BUILD_ID' \; -print 2>/dev/null | sort)
echo "releases with a built Demo: ${#BUILT[@]}"
for r in "${BUILT[@]}"; do echo "  ${r}  (BUILD_ID $(cat "${r}/apps/demo/.next/BUILD_ID" 2>/dev/null))"; done

if [ "${#BUILT[@]}" -lt 1 ]; then
    bad "no built Demo release found under ${RELEASES_ROOT} — cannot spike slot indirection"
    exit 1
fi

REL_A="${BUILT[0]}"
REL_B=""
for r in "${BUILT[@]}"; do
    if [ "${r}" != "${REL_A}" ]; then REL_B="${r}"; break; fi
done
if [ -z "${REL_B}" ]; then
    note "only one built release exists — test 3 (repoint picks up a new release) will be SKIPPED, not faked"
fi
note "release A = ${REL_A} (BUILD_ID $(cat "${REL_A}/apps/demo/.next/BUILD_ID"))"
[ -n "${REL_B}" ] && note "release B = ${REL_B} (BUILD_ID $(cat "${REL_B}/apps/demo/.next/BUILD_ID"))"

# --- Test 1: start through a slot indirection ---
log "test 1: app starts from a slot indirection and serves assets"
ln -sfn "${REL_A}" "${SLOT_A}.tmp" && mv -Tf "${SLOT_A}.tmp" "${SLOT_A}"
echo "slot A -> $(readlink -f "${SLOT_A}")"
if [ ! -x "${SLOT_A}/apps/demo/node_modules/.bin/next" ]; then
    bad "next binary not resolvable through the slot symlink (${SLOT_A}/apps/demo/node_modules/.bin/next) — pnpm symlink tree does not survive the extra indirection"
else
    ok "next binary resolves through the slot symlink"
fi

if start_slot "${UNIT_A}" "${SLOT_A}" "${SLOT_A_PORT}"; then
    code="$(wait_for_port "http://127.0.0.1:${SLOT_A_PORT}/decisions")"
    if [[ "${code}" =~ ^2 ]]; then
        ok "slot A serves /decisions on :${SLOT_A_PORT} (${code}) started via systemd through the symlink"
        verify_assets "http://127.0.0.1:${SLOT_A_PORT}"
    else
        bad "slot A did not become healthy on :${SLOT_A_PORT} within ${START_TIMEOUT_SECS}s (last=${code})"
        dump_unit "${UNIT_A}"
    fi
else
    bad "could not start slot A"
    dump_unit "${UNIT_A}"
fi
assert_live_ok "after starting slot A"

# --- Test 2: candidate isolation — two slots at once, and not publicly reachable ---
log "test 2: two slots run concurrently without interfering"
SLOT_B_TARGET="${REL_B:-${REL_A}}"
ln -sfn "${SLOT_B_TARGET}" "${SLOT_B}.tmp" && mv -Tf "${SLOT_B}.tmp" "${SLOT_B}"
echo "slot B -> $(readlink -f "${SLOT_B}")"
if start_slot "${UNIT_B}" "${SLOT_B}" "${SLOT_B_PORT}"; then
    code_b="$(wait_for_port "http://127.0.0.1:${SLOT_B_PORT}/decisions")"
    code_a="$(http_code "http://127.0.0.1:${SLOT_A_PORT}/decisions")"
    if [[ "${code_b}" =~ ^2 ]] && [[ "${code_a}" =~ ^2 ]]; then
        ok "slots A (:${SLOT_A_PORT}) and B (:${SLOT_B_PORT}) serve concurrently; neither disturbed the other"
    else
        bad "concurrent slots unhealthy (A=${code_a} B=${code_b})"
        dump_unit "${UNIT_B}"
    fi
    note "free memory with live + 2 candidates running: $(free_mb)MB"
else
    bad "could not start slot B concurrently with slot A"
    dump_unit "${UNIT_B}"
fi

# A candidate must be loopback-only: nothing outside the server may reach it.
ext_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -n "${ext_ip}" ]; then
    ext_code="$(http_code "http://${ext_ip}:${SLOT_A_PORT}/decisions")"
    if [[ "${ext_code}" =~ ^2 ]]; then
        bad "candidate on :${SLOT_A_PORT} answered on the external interface ${ext_ip} — candidates must be loopback-only"
    else
        ok "candidate on :${SLOT_A_PORT} is not reachable via ${ext_ip} (code=${ext_code}) — loopback-only holds"
    fi
fi
assert_live_ok "with two candidates running"

# --- Test 3: repointing a slot picks up a different release ---
log "test 3: repointing a slot's indirection picks up the new release"
if [ -z "${REL_B}" ]; then
    note "SKIPPED — needs two distinct built releases; only ${REL_A} exists. Re-run after the next Demo deploy."
else
    before_id="$(build_id "${SLOT_A}")"
    stop_slot "${UNIT_A}"
    ln -sfn "${REL_B}" "${SLOT_A}.tmp" && mv -Tf "${SLOT_A}.tmp" "${SLOT_A}"
    after_id="$(build_id "${SLOT_A}")"
    if start_slot "${UNIT_A}" "${SLOT_A}" "${SLOT_A_PORT}"; then
        code="$(wait_for_port "http://127.0.0.1:${SLOT_A_PORT}/decisions")"
        if [[ "${code}" =~ ^2 ]] && [ "${before_id}" != "${after_id}" ]; then
            ok "repointing slot A ${before_id} -> ${after_id} and restarting served the new release"
        elif [[ "${code}" =~ ^2 ]]; then
            bad "slot A restarted healthy but BUILD_ID did not change (${before_id}) — the repoint did not take effect"
        else
            bad "slot A did not come back healthy after repointing (last=${code})"
            dump_unit "${UNIT_A}"
        fi
    else
        bad "could not restart slot A after repointing"
        dump_unit "${UNIT_A}"
    fi
fi
assert_live_ok "after the spike"

log "verdict"
if [ "${FAIL_COUNT}" -eq 0 ]; then
    echo "SPIKE PASSES — slot-based release indirection is viable; the paired-slot layout in #820 can proceed."
    note "VERDICT: slot indirection viable — paired-slot layout can proceed"
else
    echo "SPIKE FAILS (${FAIL_COUNT}) — record the failing step on #835. Fallback per the PRD is self-contained build output or a per-slot dependency install; #836 must decide on this evidence." >&2
    note "VERDICT: slot indirection NOT proven — ${FAIL_COUNT} failing checks; #836 must weigh the fallback"
fi
exit "${FAIL_COUNT}"
