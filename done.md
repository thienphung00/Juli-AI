# Definition of Done — Issue #221

Checklist for `scripts/validate/check_done_md.py`. P1.8-10 RRAA loop exit gate.

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-221.json`
- [x] `artifacts/reviews/review-issue-221.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue221_rraa_loop` passes
- [x] Frontend: regressions `test_issue200_p18_9_exit_gate`, `test_issue218_decisions_rraa_cards` pass
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] Screenshot artifacts: `home-growth-*`, `decisions-recommended-growth-*` re-baselined
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| Handoff | `docs/handoffs/issue-221-review.md` |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-221.json` |
| Validation | `artifacts/validation/validation-issue-221.json` (CI-generated) |
