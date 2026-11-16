#!/usr/bin/env bash
# fasttrack/bin/tag-deploy.sh <full-sha> --session <name> [--push]
#
# The ONLY way a fast-track deploy tag gets made. Owner-run (auto mode blocks agents
# from pushing tags, and the deploy is a human-in-the-loop step):
#   ! /path/to/worktree/fasttrack/bin/tag-deploy.sh <sha> --session <name> --push
# Without --push it runs every check and prints what it would do (agents may run that).
#
# Refuses unless:
#   - <sha> is a full 40-char sha and is the current tip of origin/fasttrack/optimize-product
#     (or an ancestor of it, with a warning);
#   - the local deploy gate is complete for the sha's TREE (fasttrack/gate_status.py);
#   - no earlier deploy tag is still running (fasttrack/state.py);
# then makes ONE tag (never --tags), pushes it, and records it in the shared state.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}" || exit 2
DEPLOY_BRANCH="fasttrack/optimize-product"
PY="${PYTHON:-}"; for c in "${REPO_ROOT}/.venv/bin/python" /Users/macos/Juli-AI-v2/juli/.venv/bin/python python3; do
  [ -n "${PY}" ] && break; command -v "$c" >/dev/null 2>&1 && PY="$c"; done

SHA=""; SESSION=""; PUSH=0
while [ $# -gt 0 ]; do
  case "$1" in
    --session) SESSION="${2:-}"; shift 2 ;;
    --push) PUSH=1; shift ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) SHA="$1"; shift ;;
  esac
done
fail() { echo "REFUSED: $*" >&2; exit 1; }
[[ "${SHA}" =~ ^[0-9a-f]{40}$ ]] || fail "need a full 40-character lowercase sha (got '${SHA}')"
[ -n "${SESSION}" ] || fail "--session <name> is required (it is recorded in the shared state)"

git fetch -q origin "${DEPLOY_BRANCH}" || fail "cannot fetch origin/${DEPLOY_BRANCH}"
TIP="$(git rev-parse "origin/${DEPLOY_BRANCH}")"
git cat-file -e "${SHA}^{commit}" 2>/dev/null || fail "${SHA} is not a commit here (fetch first)"
git merge-base --is-ancestor "${SHA}" "${TIP}" || fail "${SHA:0:8} is not on origin/${DEPLOY_BRANCH} (tip ${TIP:0:8}) — merge/push it first"
[ "${SHA}" = "${TIP}" ] || echo "WARN: ${SHA:0:8} is behind the tip ${TIP:0:8}; deploying an older commit"

echo "== local deploy gate"
"${PY}" fasttrack/gate_status.py "${SHA}" || fail "the local gate is not complete for this tree — run fasttrack/predeploy.sh on it"

echo "== shared state"
"${PY}" fasttrack/state.py check --session "${SESSION}" >"${TMPDIR:-/tmp}/tag-deploy-check.$$" 2>&1; RC=$?
cat "${TMPDIR:-/tmp}/tag-deploy-check.$$"; rm -f "${TMPDIR:-/tmp}/tag-deploy-check.$$"
# Only the "tag still running" blocker matters here; branch checks don't apply to a tip sha.
[ "${RC}" = 0 ] || "${PY}" fasttrack/state.py --json show | "${PY}" -c '
import json,sys; t=json.load(sys.stdin)["tags"]
sys.exit(1 if t and t[-1].get("conclusion") in (None,"pending","in_progress","queued") else 0)' \
  || fail "an earlier deploy tag has no result yet"

TAG="fasttrack-deploy-$(date -u +%Y%m%dT%H%MZ)"
git rev-parse -q --verify "refs/tags/${TAG}" >/dev/null && fail "tag ${TAG} already exists locally — wait a minute"
echo "== plan: git tag ${TAG} ${SHA} && git push origin ${TAG}"
if [ "${PUSH}" != 1 ]; then echo "(dry run — the owner adds --push)"; exit 0; fi

git tag "${TAG}" "${SHA}" || fail "git tag failed"
git push origin "${TAG}" || { git tag -d "${TAG}" >/dev/null; fail "push failed; local tag removed"; }
"${PY}" fasttrack/state.py tag-record "${TAG}" "${SHA}" --session "${SESSION}"
echo "pushed ${TAG}. Watch it: ${PY} fasttrack/bin/deploy_watch.py ${TAG}"
