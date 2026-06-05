# Definition of Done — Issue #115

Checklist for `scripts/validate/check_done_md.py`. Workspace mode: Seller dark / Affiliate out-of-scope (P1-0).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-115.json`
- [x] `artifacts/reviews/review-issue-115.json` written; review `status` is `PASS`
- [x] Frontend: `npm test` passes (129 tests)
- [x] Frontend: PR Validation `lint-and-typecheck`, `test`, `frontend` jobs pass
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-115.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | Updated — affiliate out-of-scope invariant |
| Handoff | N/A |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-115.json` |
| Validation | `artifacts/validation/validation-issue-115.json` |
