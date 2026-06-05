# Definition of Done — Issue #116

Checklist for `scripts/validate/check_done_md.py`. Rules-based seller-stage router (P1-6).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-116.json`
- [x] `artifacts/reviews/review-issue-116.json` written; review `status` is `PASS`
- [x] Frontend: `npm test` passes (142 tests)
- [x] Frontend: PR Validation `lint-and-typecheck`, `test`, `frontend` jobs pass
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-116.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | N/A — utility module under web/src/lib, no public route change |
| Handoff | N/A |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-116.json` |
| Validation | `artifacts/validation/validation-issue-116.json` |
