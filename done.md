# Definition of Done — Issue #198

Checklist for `scripts/validate/check_done_md.py`. Workflow Templates sub-tab — advanced per-workflow settings (mock) (ADR-028 P1.8-9).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-198.json`
- [x] `artifacts/reviews/review-issue-198.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue198` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-198.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/src/lib/decisions/MODULE.md` | Documents Workflow Templates shell |
| Handoff | `docs/handoffs/issue-198-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-198.json` |
| Validation | `artifacts/validation/validation-issue-198.json` |
