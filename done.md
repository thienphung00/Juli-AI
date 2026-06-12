# Definition of Done — Issue #193

Checklist for `scripts/validate/check_done_md.py`. Home read-only shell — Shop Status hero + top-3 decision preview (ADR-028 P1.8-9).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-193.json`
- [x] `artifacts/reviews/review-issue-193.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue193` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-193.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/src/lib/operations/MODULE.md` | Documents HomeSummaryShell split |
| Handoff | `docs/handoffs/issue-193-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-193.json` |
| Validation | `artifacts/validation/validation-issue-193.json` |
