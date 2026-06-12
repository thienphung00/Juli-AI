# Definition of Done — Issue #210

Checklist for `scripts/validate/check_done_md.py`. Align AI Chat and Reports copy with seller vocabulary system.

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-210.json`
- [x] `artifacts/reviews/review-issue-210.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue210` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-210.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| Handoff | `docs/handoffs/issue-210-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-210.json` |
| Validation | `artifacts/validation/validation-issue-210.json` |
