# Definition of Done — Issue #199

Checklist for `scripts/validate/check_done_md.py`. Juli Chat decision context (ADR-028 P1.8-9).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-199.json`
- [x] `artifacts/reviews/review-issue-199.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue199` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-199.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/src/lib/decisions/MODULE.md` | Documents chat-context exports |
| Handoff | `docs/handoffs/issue-199-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-199.json` |
| Validation | `artifacts/validation/validation-issue-199.json` |
