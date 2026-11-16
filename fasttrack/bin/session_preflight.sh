#!/usr/bin/env bash
# fasttrack/bin/session_preflight.sh — 30-second check BEFORE a long session or a headless run.
#
# Why: sessions ended with nothing done on "Credit balance is too low", an invalid
# ANTHROPIC_CUSTOM_HEADERS value or an API-key workspace mismatch, and re-sending the prompt
# never helped (/insights 2026-11-16). This prints the active auth, the ANTHROPIC_* variables
# (masked), validates custom headers, and makes one tiny capped call. It ends with one line:
# OK, or the single fix.
#
#   fasttrack/bin/session_preflight.sh            # includes a ~$0.06 test call
#   fasttrack/bin/session_preflight.sh --no-call
set -uo pipefail
CLAUDE="${CLAUDE_BIN:-$(command -v claude || echo "${HOME}/.local/bin/claude")}"
CALL=1; [ "${1:-}" = "--no-call" ] && CALL=0
FIX=""

echo "== auth"
AUTH="$("${CLAUDE}" auth status 2>&1)" || FIX="${FIX:-not logged in: run \`claude auth login\`}"
printf '%s\n' "${AUTH}" | grep -E '"(loggedIn|authMethod|apiProvider|loginExpiresAt)"' || printf '%s\n' "${AUTH}" | head -5

echo "== ANTHROPIC_* environment (values masked)"
FOUND=0
while IFS='=' read -r k v; do
  case "$k" in ANTHROPIC_*) FOUND=1; printf '  %s=%s…(%d chars)\n' "$k" "${v:0:4}" "${#v}" ;; esac
done < <(env)
[ "${FOUND}" = 1 ] || echo "  (none set: the claude.ai login is used)"
if [ -n "${ANTHROPIC_API_KEY:-}" ] && printf '%s' "${AUTH}" | grep -q '"authMethod": "claude.ai"'; then
  echo "  NOTE: ANTHROPIC_API_KEY is set while logged in with claude.ai. The key, and its workspace's credits, may take precedence."
fi
if [ -n "${ANTHROPIC_CUSTOM_HEADERS:-}" ]; then
  while IFS= read -r line; do
    [ -z "${line}" ] && continue
    if ! [[ "${line}" =~ ^[A-Za-z0-9-]+:\ ?.+$ ]]; then
      FIX="${FIX:-ANTHROPIC_CUSTOM_HEADERS line is not 'Name: value' (got '${line:0:30}…'): fix or unset it}"
    fi
  done <<<"${ANTHROPIC_CUSTOM_HEADERS}"
fi

if [ "${CALL}" = 1 ] && [ -z "${FIX}" ]; then
  echo "== test call (sonnet, no MCP, \$0.15 cap)"
  OUT="$("${CLAUDE}" -p 'Reply with exactly: ok' --model sonnet --output-format json --strict-mcp-config \
        --disable-slash-commands --max-budget-usd 0.15 2>&1)"
  if printf '%s' "${OUT}" | grep -q '"is_error":false'; then
    echo "  ok ($(printf '%s' "${OUT}" | grep -Eo '"total_cost_usd":[0-9.]+' | cut -d: -f2) USD)"
  else
    MSG="$(printf '%s' "${OUT}" | grep -Eo '"result":"[^"]{0,160}' | cut -d'"' -f4)"
    echo "  FAILED: ${MSG:-${OUT:0:200}}"
    case "${MSG}${OUT}" in
      *"Credit balance is too low"*) FIX="credit balance too low for the ACTIVE auth: switch login (/login) or top up the workspace that owns ANTHROPIC_API_KEY" ;;
      *"workspace"*|*"organization"*) FIX="API key belongs to a different workspace than the credits: use a key from the funded workspace" ;;
      *"header"*) FIX="a custom header was rejected: unset ANTHROPIC_CUSTOM_HEADERS and retry" ;;
      *"rate"*|*"limit"*) FIX="usage/rate limit reached: wait for the reset shown by /usage, or switch auth" ;;
      *) FIX="test call failed: read the message above. Don't re-send the same prompt." ;;
    esac
  fi
fi
echo
if [ -z "${FIX}" ]; then echo "preflight: OK"; exit 0; fi
echo "preflight: FIX -> ${FIX}"; exit 1
