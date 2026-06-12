# Definition of Done — Issue #192

Checklist for `scripts/validate/check_done_md.py`. Decision view-model mapping workflow_recommendations → Decision envelopes (P1.8-9).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-192.json`
- [x] `artifacts/reviews/review-issue-192.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_decisions_view_model` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-192.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/src/lib/decisions/MODULE.md` | Documents public interface |
| Handoff | `docs/handoffs/issue-192-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-192.json` |
| Validation | `artifacts/validation/validation-issue-192.json` |
