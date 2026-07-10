#!/usr/bin/env bash
# Remove local build artifacts and dependency trees (all gitignored).
# Safe to run after branch switches, parallel worktrees, or stale cache issues.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "Cleaning gitignored artifacts under $ROOT ..."

rm -rf node_modules web/node_modules
rm -rf apps/*/node_modules packages/*/node_modules 2>/dev/null || true
rm -rf .next web/.next apps/*/.next 2>/dev/null || true
rm -rf __pycache__ .pytest_cache .turbo .coverage .coverage.*
rm -rf .worktrees/
find . -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

echo "Done. Reinstall with: pip install -e '.[dev]' (or project venv) and cd web && pnpm install"
