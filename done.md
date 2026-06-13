# Definition of Done — Issue #217

Checklist for `scripts/validate/check_done_md.py`. Home Reward charts + CTAs (P1.8-10).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-217.json`
- [x] `artifacts/reviews/review-issue-217.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue217_home_reward_charts` passes
- [x] Frontend: `npm run type-check` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-217.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| Handoff | `docs/handoffs/issue-217-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-217.json` |
| Validation | `artifacts/validation/validation-issue-217.json` |
