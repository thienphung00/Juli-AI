# Definition of Done — Issue #234

Checklist for `scripts/validate/check_done_md.py`. Inventory metrics zero-extension CTA state (P1.8-10 B3.3).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-234.json`
- [x] `artifacts/reviews/review-issue-234.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_issue234_zero_extension_cta` passes
- [x] Frontend: `npx tsc --noEmit` clean
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-234.json` exists with `status: "PASS"` (CI generate-validation-artifact job)
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| Handoff | inline in PR #243 |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-234.json` |
| Validation | `artifacts/validation/validation-issue-234.json` (CI-generated) |
