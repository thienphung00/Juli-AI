# Handoff: review → validate — Issue #{N}

## Issue
- **#{N}** — {title}

## PR
- #{pr} — {url}
- Branch: `{branch}` → `main`

## Issues found & fixed
| Issue | Domain | Fix | Status |
|-------|--------|-----|--------|

## Review artifact (required)
- Path: `artifacts/reviews/review-issue-{N}.json`
- `status`: {PASS | PASS_WITH_WARNINGS | FAIL}
- `reviewFailures`: {count}
- `sourceImplementationArtifact`: `artifacts/implementations/implementation-issue-{N}.json`

Generator: `python scripts/ci/generate_review_artifact.py --issue {N}`

## Validation gates (local)
- pytest: ✓
- ruff / eslint: ✓
- mypy / tsc: ✓

## Ready for validate
Run: `python scripts/ci/generate_validation_artifact.py --issue {N}`

Do not hand off to `ship` until validation artifact has `readyForMerge: true`.
