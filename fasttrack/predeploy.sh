#!/usr/bin/env bash
# fasttrack/predeploy.sh — run the fast-track DEPLOY GATE locally, before any tag.
#
# Why: 18 of 32 deploy runs (2026-11-08..16) failed on jobs that were never run
# locally (eslint, bandit, whole-package mypy, unit shards, check.sh + Postgres).
# This mirrors the gate jobs of .github/workflows/fasttrack-deploy.yml one to one:
#
#   job        mirrors                                   command
#   heads      plan (migration heads)                    infra/scripts/migration_heads.py heads -> exactly 1
#   frontend   frontend                                  pnpm lint/type-check/test demo, @juli/ui, @juli/utils, landing
#   static     static                                    mypy backend/src/juli_backend ; bandit -ll
#   unit       backend-unit (all 4 shards, serially)     pytest tests/unit -m "not live"
#   check      check (all 4 shards = --shard 1/1)        fasttrack/check.sh --since origin/main (throwaway Postgres)
#
# NOT mirrored (need prod secrets/VPS): build artifacts, backup, deploy, health check.
#
# A run is valid for tag-deploy.sh only when: mode=full, every job PASS, the tree was
# clean, and HEAD contained origin/fasttrack/optimize-product (= a trial merge with the
# current tip). The record is keyed by the commit's TREE hash, so the owner's merge
# commit of an up-to-date PR (same tree, new sha) is still covered.
#
# Usage:
#   fasttrack/predeploy.sh                 full gate (serial; ~45-70 min). Required before "ready".
#   fasttrack/predeploy.sh --fast          changed-files iteration loop (NOT valid for a tag)
#   fasttrack/predeploy.sh --jobs a,b      run only some jobs (NOT valid for a tag)
#   fasttrack/predeploy.sh --dry-run       print the plan and preflight only
#
# Env: PYTHON (default: <repo>/.venv, else /Users/macos/Juli-AI-v2/juli/.venv), CHECK_DATABASE_URL
# (throwaway Postgres for check.sh; else check.sh starts docker postgres:16), NODE_OPTIONS
# (default --no-webstorage, Node 26), JULI_FASTTRACK_STATE_DIR (see fasttrack/state.py).
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}" || exit 2
DEPLOY_BRANCH="fasttrack/optimize-product"
ALL_JOBS=(heads frontend static unit check)
MODE="full"; JOBS=("${ALL_JOBS[@]}"); DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --fast) MODE="fast"; shift ;;
    --jobs) [ $# -ge 2 ] || { echo "--jobs needs a list" >&2; exit 2; }; IFS=, read -r -a JOBS <<<"$2"; MODE="partial"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
for j in "${JOBS[@]}"; do
  [[ " ${ALL_JOBS[*]} " == *" $j "* ]] || { echo "unknown job: $j (have: ${ALL_JOBS[*]})" >&2; exit 2; }
done

# ---------------------------------------------------------------- preflight
if [ -z "${PYTHON:-}" ]; then
  for c in "${REPO_ROOT}/.venv/bin/python" /Users/macos/Juli-AI-v2/juli/.venv/bin/python; do
    [ -x "$c" ] && { PYTHON="$c"; break; }
  done
fi
[ -n "${PYTHON:-}" ] || { echo "FAIL: no python; set PYTHON=" >&2; exit 2; }
export PYTHON
# A worktree's installed juli_backend can point at ANOTHER checkout (memory: juli-worktree-pytest-pythonpath).
export PYTHONPATH="${REPO_ROOT}/backend/src:${REPO_ROOT}"
export NODE_OPTIONS="${NODE_OPTIONS:---no-webstorage}"
# Never let any real database reach a gate (check.sh pins these too).
unset DATABASE_URL DATABASE_DIRECT_URL SUPABASE_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_DB_URL

STATE_DIR="${JULI_FASTTRACK_STATE_DIR:-$(cd "$(git rev-parse --git-common-dir)" && pwd)/fasttrack-state}"
SHA="$(git rev-parse HEAD)"; TREE="$(git rev-parse 'HEAD^{tree}')"
OUT_DIR="${STATE_DIR}/predeploy/${TREE}"
mkdir -p "${OUT_DIR}" || exit 2

PRE_FAIL=()
CLEAN=1
[ -z "$(git status --porcelain --untracked-files=no)" ] || { CLEAN=0; PRE_FAIL+=("tree has uncommitted changes to tracked files"); }
if git fetch -q origin "${DEPLOY_BRANCH}" 2>/dev/null; then
  TIP="$(git rev-parse "origin/${DEPLOY_BRANCH}")"
else
  TIP="$(git rev-parse "origin/${DEPLOY_BRANCH}" 2>/dev/null || echo unknown)"
  PRE_FAIL+=("could not fetch origin/${DEPLOY_BRANCH} (network?) — tip ${TIP:0:8} may be stale")
fi
CONTAINS_TIP=0
git merge-base --is-ancestor "${TIP}" HEAD 2>/dev/null && CONTAINS_TIP=1
[ "${CONTAINS_TIP}" = 1 ] || PRE_FAIL+=("HEAD does not contain origin/${DEPLOY_BRANCH} ${TIP:0:8} — merge it first (trial merge)")
FREE_GB="$(df -g "${REPO_ROOT}" | awk 'NR==2{print $4}')"
[ "${FREE_GB:-0}" -ge 5 ] || PRE_FAIL+=("only ${FREE_GB} GB free — need >= 5 (memory: disk filled 2026-11-11)")
if [[ " ${JOBS[*]} " == *" frontend "* ]] && [ ! -d "${REPO_ROOT}/node_modules" ]; then
  PRE_FAIL+=("no node_modules in this worktree — run pnpm install --frozen-lockfile (owner, if the sandbox blocks it)")
fi

echo "predeploy: sha ${SHA:0:12} tree ${TREE:0:12} mode ${MODE} jobs ${JOBS[*]}"
echo "           tip ${TIP:0:12} contains-tip=${CONTAINS_TIP} clean=${CLEAN} free=${FREE_GB}GB"
for f in "${PRE_FAIL[@]+"${PRE_FAIL[@]}"}"; do echo "PREFLIGHT  ${f}"; done
[ "${DRY}" = 1 ] && exit 0

# ---------------------------------------------------------------- jobs
declare -a RESULTS=()
FAILED=0
count_tests() {  # count_tests <log> <pytest|vitest>  -> number of passed tests (0 if none found)
  local n=0
  if [ "$2" = pytest ]; then
    n="$(grep -Eo '[0-9]+ passed' "$1" | awk '{s+=$1} END{print s+0}')"
  else
    n="$(grep -Eo 'Tests +[0-9]+ passed' "$1" | grep -Eo '[0-9]+' | awk '{s+=$1} END{print s+0}')"
  fi
  echo "${n:-0}"
}
run_job() {  # run_job <name> <kind:pytest|vitest|none> <command...>
  local name="$1" kind="$2"; shift 2
  local log="${OUT_DIR}/${name}.log" t0 rc tests status
  t0="$(date +%s)"
  printf '\n==================== %s ====================\n%s\n' "${name}" "$*"
  ( "$@" ) >"${log}" 2>&1; rc=$?
  tail -n 15 "${log}"
  tests=""
  if [ "${kind}" != none ]; then
    tests="$(count_tests "${log}" "${kind}")"
    # A gate that ran 0 tests is a FAIL, never a pass (zsh word-split incident, S1 2026-11-15).
    if [ "${rc}" -eq 0 ] && [ "${tests}" -eq 0 ]; then rc=97; echo ">>> ${name}: 0 tests ran — treated as FAIL"; fi
  fi
  status=PASS; [ "${rc}" -eq 0 ] || { status=FAIL; FAILED=1; }
  local rec
  rec="$(printf '{"job":"%s","status":"%s","rc":%d,"seconds":%d,"tests":%s,"mode":"%s","sha":"%s","tree":"%s","tip":"%s","clean":%d,"contains_tip":%d,"finished_at":"%s","log":"%s"}' \
    "${name}" "${status}" "${rc}" "$(( $(date +%s) - t0 ))" "${tests:-null}" "${MODE}" "${SHA}" "${TREE}" "${TIP}" "${CLEAN}" "${CONTAINS_TIP}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${log}")"
  RESULTS+=("${rec}")
  # Per-job record: the gate for a tree is the union of its latest job records, so the
  # owner can run one job outside the sandbox (e.g. check, which needs Postgres).
  [ "${MODE}" = fast ] || echo "${rec}" >"${OUT_DIR}/job-${name}.json"
  echo ">>> ${name}: ${status} (rc ${rc}${tests:+, ${tests} passed})"
}

job_heads() {
  local heads
  heads="$("${PYTHON}" infra/scripts/migration_heads.py heads \
    --migrations-dir backend/src/juli_backend/database/migrations/versions)" || return 1
  echo "heads: ${heads}"
  [ "$(printf '%s\n' "${heads}" | grep -c .)" -eq 1 ] || { echo "FAIL: expected exactly 1 alembic head"; return 1; }
}
job_frontend() {
  pnpm lint:demo && pnpm type-check:demo && pnpm test:demo \
    && pnpm --filter @juli/ui test && pnpm --filter @juli/utils test \
    && pnpm lint:landing && pnpm type-check:landing && pnpm test:landing
}
job_static() {
  "${PYTHON}" -m mypy --config-file backend/pyproject.toml backend/src/juli_backend || return 1
  "${PYTHON}" -m bandit -r backend/src/juli_backend -ll
}
job_unit() {
  export JULI_REQUIRE_ARCHIVED_COMMITS=1
  local refspecs files=()
  refspecs="$("${PYTHON}" -c 'from eval.negative_dataset import archive_fetch_refspecs as f; print(" ".join(f()))')" || return 1
  # shellcheck disable=SC2086 # refspecs is a space-separated list by design
  git fetch -q --no-tags origin ${refspecs} || { echo "FAIL: could not fetch archived evidence refs"; return 1; }
  while IFS= read -r f; do files+=("$f"); done < <(find tests/unit -type f -name 'test_*.py' | sort)
  echo "unit: ${#files[@]} test files"
  [ "${#files[@]}" -gt 0 ] || return 1
  # Sandbox worktrees are sparse checkouts without .claude/ (memory: sandbox-worktree-sparse-checkout).
  # Exactly these 6 tests read .claude/ and can only fail there; CI's full checkout still runs them.
  local desel=()
  if [ ! -d "${REPO_ROOT}/.claude" ]; then
    local t
    for t in test_hook_blocks_on_a_failing_checkout test_hook_allows_when_the_escape_hatch_is_set \
             test_hook_allows_a_healthy_checkout test_hook_fails_open_when_the_engine_is_missing \
             test_hook_ignores_edits_outside_the_repo; do
      desel+=(--deselect "tests/unit/test_checkout_preflight.py::${t}")
    done
    desel+=(--deselect "tests/unit/test_tts_open_toolkit_wiring.py::test_claude_pointer_routes_tiktok_work_to_the_cli")
    echo "unit: sparse checkout without .claude/ — deselecting $(( ${#desel[@]} / 2 )) .claude-reading tests (CI runs them)"
  fi
  "${PYTHON}" -X faulthandler -m pytest "${files[@]}" "${desel[@]+"${desel[@]}"}" -m "not live" -q --tb=short -p no:cacheprovider
}
job_unit_fast() {
  local files=()
  while IFS= read -r f; do [ -f "$f" ] && files+=("$f"); done < <(git diff --name-only "origin/${DEPLOY_BRANCH}"...HEAD -- 'tests/unit/**/test_*.py' 'tests/unit/test_*.py')
  [ "${#files[@]}" -gt 0 ] || { echo "no changed unit test files"; echo "0 passed"; return 0; }
  "${PYTHON}" -m pytest "${files[@]}" -m "not live" -q --tb=short -p no:cacheprovider
}
job_check() {
  ./fasttrack/check.sh --since origin/main
}

for j in "${JOBS[@]}"; do
  case "${j}" in
    heads)    run_job heads none job_heads ;;
    frontend) run_job frontend vitest job_frontend ;;
    static)   run_job static none job_static ;;
    unit)     if [ "${MODE}" = fast ]; then run_job unit none job_unit_fast; else run_job unit pytest job_unit; fi ;;
    check)    if [ "${MODE}" = fast ]; then run_job check none ./fasttrack/check.sh --since "origin/${DEPLOY_BRANCH}" --skip-migrations --skip-gitleaks;
              else run_job check none job_check; fi ;;
  esac
done

# ---------------------------------------------------------------- record
printf '{"at":"%s","kind":"predeploy","sha":"%s","tree":"%s","mode":"%s","jobs":"%s","failed":%d}\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SHA}" "${TREE}" "${MODE}" "${JOBS[*]}" "${FAILED}" >>"${STATE_DIR}/events.jsonl"

printf '\n==================== summary ====================\n'
for r in "${RESULTS[@]}"; do echo "${r}"; done
for f in "${PRE_FAIL[@]+"${PRE_FAIL[@]}"}"; do echo "PREFLIGHT FAIL: ${f}"; done
if [ "${FAILED}" != 0 ] && [[ " ${JOBS[*]} " == *" check "* ]] && grep -qiE 'docker|could not connect|connection refused|Operation not permitted' "${OUT_DIR}/check.log" 2>/dev/null; then
  echo "HINT: check needs a throwaway Postgres the sandbox cannot reach. Owner runs:"
  echo "  ! cd ${REPO_ROOT} && CHECK_DATABASE_URL=postgresql://localhost/predeploy_check ./fasttrack/predeploy.sh --jobs check"
fi
echo
"${PYTHON}" "${REPO_ROOT}/fasttrack/gate_status.py" "${TREE}" --state-dir "${STATE_DIR}"
GATE=$?
[ "${#PRE_FAIL[@]}" -eq 0 ] || { echo "predeploy: FAILED preflight"; exit 1; }
[ "${FAILED}" = 0 ] || { echo "predeploy: FAILED"; exit 1; }
[ "${GATE}" = 0 ] && { echo "predeploy: OK — tree ${TREE:0:12} is valid for a tag"; exit 0; }
echo "predeploy: OK (${MODE}) — gate not complete for this tree yet (see above)"; exit 0
