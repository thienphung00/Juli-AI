# Handoff: validate → ship — Issue #{N}

## Issue
- **#{N}** — {title}

## PR
- #{pr} — {url}
- Branch: `{branch}` → `main`

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
