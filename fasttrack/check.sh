#!/usr/bin/env bash
# fasttrack/check.sh — the pre-deploy check for the fast-track branch (DECISIONS D8,
# ACCEPTANCE AC-0.4). Run by .github/workflows/fasttrack-deploy.yml AFTER the
# production backup job, and runnable locally.
#
# Steps, in order (any failure -> non-zero exit, after the summary is printed):
#   1. migrations  — `alembic upgrade head` on a THROWAWAY Postgres, then the
#                    public-schema privilege check, `downgrade -1`, `upgrade head`
#                    (the slim core of pr.yml's `migration-check` job).
#   2. isolation   — tests/integration/test_two_tenant_isolation_proof.py
#                    (pr.yml's `two-tenant-isolation-proof` job), on that database.
#   3. gitleaks    — commits since the base ref plus uncommitted changes, with the
#                    repo's .gitleaks.toml.
#   4. ruff        — `ruff check` + `ruff format --check` on changed Python files,
#                    with the same per-path configs as .pre-commit-config.yaml.
#   5. pytest      — test files touched since the base ref, plus tests whose name
#                    matches a changed source module (test_<module>.py,
#                    test_<module>_*.py).
#
# Usage:
#   fasttrack/check.sh [--since <ref>] [--skip-migrations] [--skip-gitleaks]
#
#   --since <ref>        base ref for "changed" (default: origin/main). The diff is
#                        taken from merge-base(<ref>, HEAD) to the working tree.
#   --skip-migrations    skip step 1. Step 2 then runs only if CHECK_DATABASE_URL
#                        points at a database already at head; otherwise it is
#                        reported SKIPPED.
#   --skip-gitleaks      skip step 3 (local use only; the deploy never passes it).
#
# Database for steps 1, 2 and 5:
#   CHECK_DATABASE_URL   a THROWAWAY Postgres (CI passes its service container).
#                        Everything in it may be dropped. Only localhost-style hosts
#                        are accepted unless CHECK_DATABASE_URL_ALLOW_REMOTE=1.
#   otherwise            a disposable `postgres:16` docker container is started and
#                        removed on exit.
#
# Other env: PYTHON (default: ./.venv/bin/python, else python3), RUFF (default: ruff
# on PATH, else `$PYTHON -m ruff`), GITLEAKS (default: gitleaks on PATH).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

SINCE="origin/main"
SKIP_MIGRATIONS=0
SKIP_GITLEAKS=0

usage() { sed -n '2,40p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --since) [ $# -ge 2 ] || { echo "--since needs a ref" >&2; exit 2; }; SINCE="$2"; shift 2 ;;
        --since=*) SINCE="${1#--since=}"; shift ;;
        --skip-migrations) SKIP_MIGRATIONS=1; shift ;;
        --skip-gitleaks) SKIP_GITLEAKS=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1 (see --help)" >&2; exit 2 ;;
    esac
done

# --------------------------------------------------------------------------------------
# Environment
# --------------------------------------------------------------------------------------

if [ -z "${PYTHON:-}" ]; then
    if [ -x "${REPO_ROOT}/.venv/bin/python" ]; then
        PYTHON="${REPO_ROOT}/.venv/bin/python"
    else
        PYTHON="$(command -v python3 || command -v python || true)"
    fi
fi
[ -n "${PYTHON}" ] || { echo "FAIL: no python found; set PYTHON=/path/to/python" >&2; exit 2; }

# In a git worktree an installed juli_backend can point at ANOTHER checkout; this
# makes the code under test the code in this tree.
export PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}"

if [ -z "${RUFF:-}" ]; then
    if command -v ruff >/dev/null 2>&1; then RUFF="ruff"; else RUFF="${PYTHON} -m ruff"; fi
fi
GITLEAKS="${GITLEAKS:-gitleaks}"

# Never let the repo's .env (loaded by juli_backend with override=False) supply a
# database: alembic prefers DATABASE_DIRECT_URL, and a production value there would
# make the "throwaway" migration run against production. Both are pinned below to
# the throwaway database, or to empty when there is none.
export DATABASE_URL=""
export DATABASE_DIRECT_URL=""

declare -a SUMMARY=()
FAILED=0

record() {  # record <step> <PASS|FAIL|SKIPPED> <detail>
    SUMMARY+=("$(printf '%-11s %-7s %s' "$1" "$2" "$3")")
    if [ "$2" = "FAIL" ]; then FAILED=1; fi
    printf '\n>>> %s: %s — %s\n' "$1" "$2" "$3"
}

section() { printf '\n==================== %s ====================\n' "$*"; }

print_summary() {
    section "summary"
    local line
    for line in "${SUMMARY[@]}"; do printf '%s\n' "${line}"; done
    if [ "${FAILED}" -ne 0 ]; then
        echo "check.sh: FAILED"
    else
        echo "check.sh: OK"
    fi
}

# --------------------------------------------------------------------------------------
# Base ref and changed files
# --------------------------------------------------------------------------------------

if ! BASE="$(git merge-base "${SINCE}" HEAD 2>/dev/null)"; then
    echo "FAIL: cannot resolve merge-base of '${SINCE}' and HEAD (fetch it, or pass --since <ref>)" >&2
    exit 2
fi

# Committed since BASE + uncommitted + untracked; existing files only.
CHANGED_FILES="$(
    {
        git diff --name-only --diff-filter=d "${BASE}"
        git ls-files --others --exclude-standard
    } | sort -u | while IFS= read -r f; do if [ -f "${f}" ]; then printf '%s\n' "${f}"; fi; done
)"
CHANGED_PY="$(printf '%s\n' "${CHANGED_FILES}" | grep -E '\.py$' || true)"
echo "check.sh: base ${SINCE} -> merge-base ${BASE:0:12}; $(printf '%s' "${CHANGED_FILES}" | grep -c . || true) changed file(s), $(printf '%s' "${CHANGED_PY}" | grep -c . || true) Python"
echo "check.sh: python ${PYTHON} ($("${PYTHON}" --version 2>&1))"

# --------------------------------------------------------------------------------------
# Throwaway database
# --------------------------------------------------------------------------------------

DB_URL=""
DB_CONTAINER=""

# shellcheck disable=SC2329  # invoked via trap
cleanup() {
    if [ -n "${DB_CONTAINER}" ]; then
        docker rm -f "${DB_CONTAINER}" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

url_host() {
    "${PYTHON}" -c 'import sys; from urllib.parse import urlparse; print(urlparse(sys.argv[1]).hostname or "")' "$1"
}

accept_check_database_url() {
    local host
    host="$(url_host "${CHECK_DATABASE_URL}")"
    case "${host}" in
        localhost|127.0.0.1|::1|postgres) ;;
        *)
            if [ "${CHECK_DATABASE_URL_ALLOW_REMOTE:-0}" != "1" ]; then
                echo "FAIL: CHECK_DATABASE_URL host '${host}' is not local. This database is wiped by the check;" >&2
                echo "      set CHECK_DATABASE_URL_ALLOW_REMOTE=1 only if it really is throwaway." >&2
                return 1
            fi
            ;;
    esac
    DB_URL="${CHECK_DATABASE_URL}"
}

start_docker_postgres() {
    command -v docker >/dev/null 2>&1 || return 1
    docker info >/dev/null 2>&1 || return 1
    local port ready=0
    DB_CONTAINER="juli-fasttrack-check-$$"
    docker run -d --rm --name "${DB_CONTAINER}" \
        -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=test -e POSTGRES_DB=check_db \
        -p 127.0.0.1::5432 postgres:16 >/dev/null || { DB_CONTAINER=""; return 1; }
    for _ in $(seq 1 60); do
        if docker exec "${DB_CONTAINER}" pg_isready -U postgres -d check_db >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
    [ "${ready}" -eq 1 ] || { echo "FAIL: docker postgres never became ready" >&2; return 1; }
    # pg_isready can pass while the entrypoint's init restart is still pending.
    sleep 2
    port="$(docker port "${DB_CONTAINER}" 5432/tcp | head -n 1 | sed 's/.*://')"
    DB_URL="postgresql://postgres:test@127.0.0.1:${port}/check_db"
}

use_db() {
    export DATABASE_URL="${DB_URL}"
    export DATABASE_DIRECT_URL="${DB_URL}"
    # The database is throwaway by construction; tests/conftest.py requires the
    # declaration before it runs destructive suites against it.
    export JULI_TEST_DATABASE_DISPOSABLE=1
}

# --------------------------------------------------------------------------------------
# 1. Migration check
# --------------------------------------------------------------------------------------

section "1/5 migrations"
MIGRATED=0
if [ "${SKIP_MIGRATIONS}" -eq 1 ]; then
    record migrations SKIPPED "--skip-migrations"
    if [ -n "${CHECK_DATABASE_URL:-}" ] && accept_check_database_url; then
        use_db
        MIGRATED=1   # caller asserts this database is already at head
    fi
else
    db_ok=1
    if [ -n "${CHECK_DATABASE_URL:-}" ]; then
        accept_check_database_url || db_ok=0
    elif ! start_docker_postgres; then
        echo "FAIL: no throwaway Postgres. Set CHECK_DATABASE_URL=postgresql://... (a database you can lose)," >&2
        echo "      start Docker, or pass --skip-migrations." >&2
        db_ok=0
    fi
    if [ "${db_ok}" -eq 0 ]; then
        record migrations FAIL "no throwaway database"
    else
        use_db
        if "${PYTHON}" agent-runtime/scripts/ci/ensure_postgrest_client_roles.py \
            && "${PYTHON}" -m alembic upgrade head \
            && "${PYTHON}" agent-runtime/scripts/ci/check_public_schema_privileges.py \
            && "${PYTHON}" -m alembic downgrade -1 \
            && "${PYTHON}" -m alembic upgrade head; then
            head_rev="$("${PYTHON}" -m alembic current 2>/dev/null | tail -n 1 || true)"
            record migrations PASS "upgrade head / downgrade -1 / upgrade head; at ${head_rev:-head}"
            MIGRATED=1
        else
            record migrations FAIL "alembic or privilege check failed (see output above)"
        fi
    fi
fi

# --------------------------------------------------------------------------------------
# 2. Shop-isolation (two-tenant RLS) tests
# --------------------------------------------------------------------------------------

# Run pytest. In strict mode, refuse a run that passed by skipping: a Postgres test
# that cannot reach its database skips, and a green "0 passed" proves nothing. In
# lenient mode, "no tests collected" (exit 5, e.g. everything was `live`) passes.
run_pytest() {  # run_pytest <strict|lenient> <label> <pytest args...>
    local mode="$1" label="$2" out rc
    shift 2
    out="$(mktemp)"
    set +e
    "${PYTHON}" -m pytest "$@" 2>&1 | tee "${out}"
    rc="${PIPESTATUS[0]}"
    set -e
    PYTEST_LAST_LINE="$(grep -E '(passed|failed|error|skipped|no tests ran)' "${out}" | tail -n 1 | sed 's/=//g; s/^ *//; s/ *$//')"
    if [ "${mode}" = "lenient" ] && [ "${rc}" -eq 5 ]; then
        rc=0
    fi
    if [ "${mode}" = "strict" ] && [ "${rc}" -eq 0 ] && ! grep -qE '[0-9]+ passed' "${out}"; then
        rm -f "${out}"
        echo "FAIL: ${label}: pytest exited 0 but nothing passed (${PYTEST_LAST_LINE})" >&2
        return 1
    fi
    rm -f "${out}"
    return "${rc}"
}

section "2/5 shop isolation"
ISOLATION_TEST="tests/integration/test_two_tenant_isolation_proof.py"
if [ "${MIGRATED}" -ne 1 ]; then
    if [ "${SKIP_MIGRATIONS}" -eq 1 ]; then
        record isolation SKIPPED "no migrated database (--skip-migrations without CHECK_DATABASE_URL)"
    else
        record isolation FAIL "no migrated database (migration step failed)"
    fi
elif run_pytest strict isolation "${ISOLATION_TEST}" -q --tb=short -k isolation_proof -p no:cacheprovider; then
    if grep -q ' skipped' <<<"${PYTEST_LAST_LINE}"; then
        record isolation FAIL "some isolation tests skipped: ${PYTEST_LAST_LINE}"
    else
        record isolation PASS "${PYTEST_LAST_LINE}"
    fi
else
    record isolation FAIL "${PYTEST_LAST_LINE:-pytest failed}"
fi

# --------------------------------------------------------------------------------------
# 3. gitleaks
# --------------------------------------------------------------------------------------

section "3/5 gitleaks"
if [ "${SKIP_GITLEAKS}" -eq 1 ]; then
    record gitleaks SKIPPED "--skip-gitleaks"
elif ! command -v "${GITLEAKS}" >/dev/null 2>&1; then
    echo "gitleaks is not installed. Install it (v8.19+ for the 'git' subcommand):" >&2
    echo "    brew install gitleaks          # macOS" >&2
    echo "    https://github.com/gitleaks/gitleaks/releases  # linux binary" >&2
    echo "or pass --skip-gitleaks for a local run." >&2
    record gitleaks FAIL "gitleaks binary not found"
else
    gl_ok=1
    if [ "$(git rev-list --count "${BASE}..HEAD")" -gt 0 ]; then
        "${GITLEAKS}" git --config .gitleaks.toml --redact --no-banner \
            --log-opts="${BASE}..HEAD" . || gl_ok=0
    fi
    # Uncommitted changes too (unstaged, then staged): what a local run is about to commit.
    "${GITLEAKS}" git --config .gitleaks.toml --redact --no-banner --pre-commit . || gl_ok=0
    "${GITLEAKS}" git --config .gitleaks.toml --redact --no-banner --pre-commit --staged . || gl_ok=0
    if [ "${gl_ok}" -eq 1 ]; then
        record gitleaks PASS "no leaks in ${BASE:0:12}..HEAD + working tree"
    else
        record gitleaks FAIL "leaks found (see output above)"
    fi
fi

# --------------------------------------------------------------------------------------
# 4. ruff (same per-path configs as .pre-commit-config.yaml)
# --------------------------------------------------------------------------------------

section "4/5 ruff"
RUFF_BACKEND="$(printf '%s\n' "${CHANGED_PY}" | grep -E '^(backend|tests|scripts)/' || true)"
RUFF_HARNESS="$(printf '%s\n' "${CHANGED_PY}" | grep -E '^agent-runtime/scripts/' || true)"
RUFF_OTHER="$(printf '%s\n' "${CHANGED_PY}" | grep -vE '^(backend|tests|scripts|agent-runtime/scripts)/' | grep . || true)"
ruff_ok=1
ruff_n=0
ruff_group() {  # ruff_group <files> [--config <cfg>]
    local files="$1"
    shift
    [ -n "${files}" ] || return 0
    local -a list=()
    while IFS= read -r f; do if [ -n "${f}" ]; then list+=("${f}"); fi; done <<<"${files}"
    ruff_n=$((ruff_n + ${#list[@]}))
    # shellcheck disable=SC2086  # RUFF may be "python -m ruff"
    ${RUFF} check "$@" "${list[@]}" || ruff_ok=0
    # shellcheck disable=SC2086
    ${RUFF} format --check "$@" "${list[@]}" || ruff_ok=0
}
if [ -z "${CHANGED_PY}" ]; then
    record ruff PASS "no changed Python files"
else
    echo "ruff: $(${RUFF} --version 2>&1)"
    ruff_group "${RUFF_BACKEND}" --config backend/pyproject.toml
    ruff_group "${RUFF_HARNESS}" --config ruff.toml
    ruff_group "${RUFF_OTHER}"
    if [ "${ruff_ok}" -eq 1 ]; then
        record ruff PASS "check + format clean on ${ruff_n} file(s)"
    else
        record ruff FAIL "ruff check/format failed (see output above; fix with 'ruff format' / 'ruff check --fix')"
    fi
fi

# --------------------------------------------------------------------------------------
# 5. pytest on touched tests + tests matching changed source modules
# --------------------------------------------------------------------------------------

section "5/5 pytest"
SELECTED="$(
    {
        # Test files touched directly.
        printf '%s\n' "${CHANGED_PY}" | grep -E '^tests/(.*/)?test_[^/]*\.py$' || true
        # Tests named after a changed source module: foo.py -> test_foo.py, test_foo_*.py
        printf '%s\n' "${CHANGED_PY}" \
            | grep -E '^(backend/src|agent-runtime/scripts|scripts|infra/scripts)/' \
            | while IFS= read -r src; do
                mod="$(basename "${src}" .py)"
                if [ "${mod}" = "__init__" ] || [ "${mod}" = "__main__" ] || [ "${mod}" = "conftest" ]; then
                    continue
                fi
                find tests -type f \( -name "test_${mod}.py" -o -name "test_${mod}_*.py" \) 2>/dev/null
            done
    } | grep . | sort -u || true
)"
if [ -z "${SELECTED}" ]; then
    record pytest PASS "no touched or matching test files"
else
    declare -a TEST_FILES=()
    while IFS= read -r f; do TEST_FILES+=("${f}"); done <<<"${SELECTED}"
    echo "pytest: ${#TEST_FILES[@]} file(s):"
    printf '  %s\n' "${TEST_FILES[@]}"
    if [ -n "${DB_URL}" ] && [ "${MIGRATED}" -eq 1 ]; then use_db; fi
    if [ ! -d packages/contracts/node_modules ]; then
        echo "WARN: packages/contracts/node_modules is missing; Python<->TS contract tests will fail" >&2
        echo "      with CalledProcessError. Run: pnpm install --frozen-lockfile --filter './packages/contracts...'" >&2
    fi
    # `live` tests need third-party sandbox credentials (merge_group only in pr.yml).
    if run_pytest lenient pytest "${TEST_FILES[@]}" -q --tb=short -m "not live" -p no:cacheprovider; then
        record pytest PASS "${#TEST_FILES[@]} file(s): ${PYTEST_LAST_LINE}"
    else
        record pytest FAIL "${#TEST_FILES[@]} file(s): ${PYTEST_LAST_LINE:-pytest failed}"
    fi
fi

print_summary
exit "${FAILED}"
