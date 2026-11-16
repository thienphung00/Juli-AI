#!/usr/bin/env bash
# fasttrack/bin/pg-test.sh <pytest args...>
#
# Runs Postgres-backed tests against a LOCAL THROWAWAY database only. Replaces the
# hand-written owner commands that failed ~30 % of the time (wrong path, missing
# JULI_TEST_DATABASE_DISPOSABLE / DATABASE_URL, placeholders).
#
#   fasttrack/bin/pg-test.sh tests/integration/test_x.py -k something
#
# - DATABASE_URL defaults to postgresql://localhost/juli_test; any host other than
#   localhost / 127.0.0.1 / ::1 / a unix socket is REFUSED (the suite truncates tables).
# - Every other database / Supabase variable is unset, so a stale .env cannot leak in.
# - PYTHONPATH is pinned to THIS worktree (memory: juli-worktree-pytest-pythonpath).
# - If Postgres is unreachable from this shell (the sandbox), it prints the exact
#   `!` command for the owner — absolute paths, no placeholders.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${REPO_ROOT}" || exit 2
PY="${PYTHON:-/Users/macos/Juli-AI-v2/juli/.venv/bin/python}"
URL="${JULI_PG_TEST_URL:-postgresql://localhost/juli_test}"

HOST="$("${PY}" -c 'import sys,urllib.parse as u; p=u.urlparse(sys.argv[1]); print(p.hostname or "")' "${URL}")"
case "${HOST}" in
  ""|localhost|127.0.0.1|::1) ;;
  *) echo "REFUSED: ${URL} is not a local throwaway database (host ${HOST})" >&2; exit 1 ;;
esac
[ $# -gt 0 ] || { echo "usage: fasttrack/bin/pg-test.sh <pytest args>" >&2; exit 2; }
for f in "$@"; do
  case "$f" in -*) ;; *) [ -e "${f%%::*}" ] || { echo "REFUSED: no such test path: ${f} (tests/integration vs tests/unit?)" >&2; exit 1; } ;; esac
done

if command -v pg_isready >/dev/null 2>&1 && ! pg_isready -q -d "${URL}" 2>/dev/null; then
  printf -v ARGS '%q ' "$@"
  echo "Postgres at ${URL} is unreachable from this shell (sandbox or not running). Owner runs:"
  echo "  ! cd ${REPO_ROOT} && ./fasttrack/bin/pg-test.sh ${ARGS}"
  exit 3
fi

exec env -u DATABASE_DIRECT_URL -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_DB_URL \
  -u CHECK_DATABASE_URL \
  JULI_TEST_DATABASE_DISPOSABLE=1 DATABASE_URL="${URL}" \
  PYTHONPATH="${REPO_ROOT}/backend/src:${REPO_ROOT}" \
  "${PY}" -m pytest -q -p no:cacheprovider "$@"
