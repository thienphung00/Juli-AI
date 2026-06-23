# Handoff: validate → ship — Issue #{N}

## Issue
- **#{N}** — {title}

## PR
- #{pr} — {url}
- Branch: `{branch}` → `main`

## Validation artifact (required gate)
- Path: `artifacts/validation/validation-issue-{N}.json`
- `status`: PASS
- `readyForMerge`: true
- `readyForShip`: true
- `validationFailures`: 0
- Checks: {passed}/{total} passed

**Block ship** if any gate field is missing or false.

## Review status
- Critical findings: {N} — all resolved
- Warnings: {N} — {resolved/accepted with rationale}
- Info: {N} — noted

## Test results
- All tests passing (including new + pre-existing)
- Lint: clean
- Type-check: clean

## Checklist
- [x] Tests added for all acceptance criteria
- [x] No secrets committed
- [x] Error handling on all I/O paths
- [x] Structured logging on error paths
- [x] Migrations reversible (if applicable)

## Next step
Meta Agent (Focus): emit harness optimization artifact, then `ship` if merge-ready.
