# Definition of Done — Issue #181

Checklist for `scripts/validate/check_done_md.py`. Unified approval gate + execution routing (P1.8-6).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-181.json`
- [x] `artifacts/reviews/review-issue-181.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern="test_operations_approval|test_operations_reasoning|test_clarity_card"` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-181.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | `web/src/lib/operations/MODULE.md` updated |
| Handoff | `docs/handoffs/issue-181-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-181.json` |
| Validation | `artifacts/validation/validation-issue-181.json` |
