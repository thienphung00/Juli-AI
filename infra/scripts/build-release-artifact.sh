#!/usr/bin/env bash
# Build a deployable release artifact in CI (Issue #837, slice P0-DEL-ARTIFACT, PRD #820).
#
# WHERE THIS RUNS: continuous integration only. It is the counterpart of the server
# no longer compiling — see the guard below, which refuses to run from a release
# directory. Nothing in the deploy path invokes it.
#
# WHAT IT PRODUCES — the shape ADR-058 fixed, in two halves, ready to run:
#   1. the built output (.next) for the deployable, and
#   2. its production dependency tree, resolved HERE, not resolved again on the
#      server. `pnpm deploy --prod` writes a self-contained node_modules (its own
#      .pnpm virtual store, symlinks relative to the target) into the staging
#      directory, so the tree survives being tarred and moved.
#
# ADR-058 rejected `output: 'standalone'`. Do not add it, and do not add
# `outputFileTracingRoot` — needing it is the tell that the packaging shape has
# drifted toward standalone, which is a decision this script does not get to make.
#
# The artifact is a gzipped tar so that symlinks survive; an uploaded *directory*
# would be dereferenced and the dependency tree would arrive duplicated or broken.
#
# TRACEABILITY: <stage>/release-artifact.json records the exact commit, and the
# tarball filename carries its short form. A reader with only the tarball can
# recover the commit from either.
#
# Usage:
#   ./infra/scripts/build-release-artifact.sh --app demo --commit "$GITHUB_SHA" --out dist/
#   ./infra/scripts/build-release-artifact.sh --app demo --commit "$SHA" --out dist/ --metadata-only
#
# Exit status: 0 only when the artifact exists. Any failure — install, build,
# missing build output, packaging — exits non-zero having written no tarball, so a
# failed build publishes nothing.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

APP=""
COMMIT=""
OUT_DIR=""
METADATA_ONLY=0

# The Next deployables of PRD #820. apps/dashboard is deliberately absent: it is
# npm-owned, is not a pnpm workspace member, and PRD #820 retires it from
# production rather than deploying it.
DEPLOYABLES="demo landing"

usage() {
    cat <<'USAGE'
Usage: build-release-artifact.sh --app <demo|landing> --commit <sha> --out <dir> [--metadata-only]

Builds one deployable in CI and packages its build output together with a
production dependency tree resolved in CI (ADR-058), as
<out>/juli-<app>-<short-sha>.tar.gz.

Options:
  --app NAME        Deployable to build: demo or landing.
  --commit SHA      The exact commit the artifact is built from. Recorded in
                    release-artifact.json and in the tarball filename.
  --out DIR         Directory to write the staging tree and the tarball into.
  --metadata-only   Write release-artifact.json and stop. No install, no build,
                    no tarball. Used to inspect provenance without a toolchain.
  -h, --help        Show this help and exit 0.

Command seams (override for testing; defaults are what CI runs):
  RELEASE_ARTIFACT_INSTALL_CMD   default: pnpm install --frozen-lockfile --filter @juli/<app>...
  RELEASE_ARTIFACT_BUILD_CMD     default: pnpm exec turbo run build --filter=@juli/<app> --force
USAGE
}

die() {
    printf 'FAIL: %s\n' "$1" >&2
    exit 1
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --app)           [ "$#" -ge 2 ] || die "--app needs a value"; APP="$2"; shift 2 ;;
        --commit)        [ "$#" -ge 2 ] || die "--commit needs a value"; COMMIT="$2"; shift 2 ;;
        --out)           [ "$#" -ge 2 ] || die "--out needs a value"; OUT_DIR="$2"; shift 2 ;;
        --metadata-only) METADATA_ONLY=1; shift ;;
        -h|--help)       usage; exit 0 ;;
        *)               usage >&2; die "unknown argument: $1" ;;
    esac
done

[ -n "${APP}" ]    || { usage >&2; die "--app is required"; }
[ -n "${COMMIT}" ] || { usage >&2; die "--commit is required"; }
[ -n "${OUT_DIR}" ] || { usage >&2; die "--out is required"; }

app_is_deployable=0
for candidate in ${DEPLOYABLES}; do
    [ "${candidate}" = "${APP}" ] && app_is_deployable=1
done
[ "${app_is_deployable}" -eq 1 ] || die "unknown deployable '${APP}' (expected one of: ${DEPLOYABLES})"

APP_DIR="${REPO_ROOT}/apps/${APP}"
[ -d "${APP_DIR}" ] || die "missing ${APP_DIR}"

# The whole point of this slice is that compilation left the server. Running here
# from a release directory would quietly put it back.
case "${REPO_ROOT}" in
    */releases/*) die "refusing to build from a release directory (${REPO_ROOT}). Artifacts are built in CI (#837); the server only starts processes." ;;
esac

SHORT_COMMIT="${COMMIT:0:7}"
STAGE_NAME="juli-${APP}-${SHORT_COMMIT}"
STAGE_DIR="${OUT_DIR}/${STAGE_NAME}"
TARBALL="${OUT_DIR}/${STAGE_NAME}.tar.gz"

mkdir -p "${STAGE_DIR}"

write_metadata() {
    local target="$1"
    local next_version=""
    # Read the app's manifest by absolute path: this function is called from
    # two different working directories.
    next_version="$(node -e 'const p=require(process.argv[1]);process.stdout.write((p.dependencies&&p.dependencies.next)||"")' "${APP_DIR}/package.json" 2>/dev/null || true)"
    cat >"${target}" <<JSON
{
  "schema": "juli.release-artifact/v1",
  "app": "${APP}",
  "package": "@juli/${APP}",
  "commit": "${COMMIT}",
  "commitShort": "${SHORT_COMMIT}",
  "builtAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "builtBy": "${GITHUB_WORKFLOW:-local}",
  "workflowRunId": "${GITHUB_RUN_ID:-}",
  "repository": "${GITHUB_REPOSITORY:-}",
  "packagingShape": "build-output-plus-production-dependencies",
  "packagingShapeDecision": "docs/adr/058-release-packaging-shape.md",
  "nextDependencyRange": "${next_version}",
  "node": "$(node --version 2>/dev/null || echo unknown)",
  "pnpm": "$(pnpm --version 2>/dev/null || echo unknown)",
  "startCommand": "node_modules/.bin/next start"
}
JSON
}

cd "${APP_DIR}"

if [ "${METADATA_ONLY}" -eq 1 ]; then
    write_metadata "${STAGE_DIR}/release-artifact.json"
    echo "PASS: wrote metadata only for @juli/${APP} at ${COMMIT} (no build, no artifact)."
    exit 0
fi

echo "== release artifact: @juli/${APP} @ ${COMMIT} =="

INSTALL_CMD="${RELEASE_ARTIFACT_INSTALL_CMD:-pnpm install --frozen-lockfile --filter @juli/${APP}...}"
BUILD_CMD="${RELEASE_ARTIFACT_BUILD_CMD:-pnpm exec turbo run build --filter=@juli/${APP} --force}"

cd "${REPO_ROOT}"
corepack enable pnpm 2>/dev/null || true

echo "-- resolve the workspace dependency graph --"
eval "${INSTALL_CMD}" || die "dependency install failed — no artifact produced"

# --force: git worktrees share Turborepo's local cache, and a cache hit can restore
# a .next from another checkout. A release artifact must be a real build.
echo "-- build --"
eval "${BUILD_CMD}" || die "build failed — no artifact produced"

echo "-- verify build output --"
[ -d "${APP_DIR}/.next" ] || die "${APP}: .next missing after build"
[ -d "${APP_DIR}/.next/static" ] || die "${APP}: hashed static assets missing (.next/static)"

echo "-- resolve the production dependency tree (ADR-058, half two) --"
# --prod drops devDependencies; --legacy is required because this workspace does
# not set inject-workspace-packages. The result is self-contained under the target.
rm -rf "${STAGE_DIR}"
mkdir -p "${OUT_DIR}"
pnpm --filter "@juli/${APP}" deploy --prod --legacy "${STAGE_DIR}" \
    || die "production dependency resolution failed — no artifact produced"

[ -x "${STAGE_DIR}/node_modules/.bin/next" ] \
    || die "${APP}: next is not runnable from the artifact's own dependency tree"

echo "-- stage the build output --"
# Copy .next after `pnpm deploy` so the artifact carries exactly what was just
# built, whatever the package's file list happens to include.
rm -rf "${STAGE_DIR}/.next"
cp -R "${APP_DIR}/.next" "${STAGE_DIR}/.next"
if [ -d "${APP_DIR}/public" ]; then
    rm -rf "${STAGE_DIR}/public"
    cp -R "${APP_DIR}/public" "${STAGE_DIR}/public"
fi

write_metadata "${STAGE_DIR}/release-artifact.json"

echo "-- package --"
rm -f "${TARBALL}"
tar -czf "${TARBALL}" -C "${OUT_DIR}" "${STAGE_NAME}" \
    || { rm -f "${TARBALL}"; die "packaging failed — no artifact produced"; }

echo "PASS: ${TARBALL} ($(du -sh "${TARBALL}" | cut -f1)) built from ${COMMIT}"
