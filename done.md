# Definition of Done — Issue #154

Checklist for `scripts/validate/check_done_md.py`. Rules-based listing generation (P1.6-3).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-154.json`
- [x] `artifacts/reviews/review-issue-154.json` written; review `status` is `PASS`
- [x] Frontend: `npm test` passes (200 tests)
- [x] Frontend: PR Validation `lint-and-typecheck`, `test`, `frontend` jobs pass
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-154.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | Done — `web/src/lib/workflows/new-seller/listing/MODULE.md` |
| Handoff | Done — focus, tdd, review handoffs |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-154.json` |
| Validation | `artifacts/validation/validation-issue-154.json` |
