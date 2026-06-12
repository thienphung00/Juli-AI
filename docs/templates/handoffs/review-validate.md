# Handoff: review → validate — Issue #{N}

## Issue
- **#{N}** — {title}

## PR
- #{pr} — {url}
- Branch: `{branch}` → `main`

## Issues found & fixed
| Issue | Domain | Fix | Status |
|-------|--------|-----|--------|

## Review artifact
- `artifacts/reviews/review-issue-{N}.json`

## Validation gates (local)
- pytest: ✓
- ruff / eslint: ✓
- mypy / tsc: ✓

## Ready for validate
Run: `python scripts/ci/generate_validation_artifact.py --issue {N}`
