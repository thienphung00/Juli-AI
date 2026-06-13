# Definition of Done — Issue #217 (reopen)

Checklist for `scripts/validate/check_done_md.py`. Home Real/Estimated visualizations (P1.8-10 reopen).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-217.json`
- [x] `artifacts/reviews/review-issue-217.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue217_home_reward_charts` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-217.json` exists with `status: "PASS"` (CI generate-validation-artifact job)
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| Handoff | `docs/handoffs/issue-217-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-217.json` |
| Validation | `artifacts/validation/validation-issue-217.json` (CI-generated) |
