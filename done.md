# Definition of Done — Issue #177

Checklist for `scripts/validate/check_done_md.py`. Shop profile classification + workflow catalog (P1.8-1).

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-177.json`
- [x] `artifacts/reviews/review-issue-177.json` written; review `status` is `PASS`
- [x] Frontend: `npm test` passes (classification suite 14/14; full suite 323/324 — 1 pre-existing leakage UI flake)
- [x] Frontend: PR Validation `lint-and-typecheck`, `test`, `frontend` jobs pass
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-177.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | `web/src/lib/operations/MODULE.md` added |
| Handoff | Skipped — ad-hoc build-feature pipeline |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-177.json` |
| Validation | `artifacts/validation/validation-issue-177.json` |
