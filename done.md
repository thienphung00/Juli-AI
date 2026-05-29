# Definition of Done — Issue #70

Checklist for `scripts/validate/check_done_md.py`. Covers #70 (UI-only dev perf) and #71 (spinner fix) on branch `fix/issue-70-71-ui-only-home`.

## Required

- [x] Issue acceptance criteria each have a named test mapping in `artifacts/reviews/review-issue-70.json`
- [x] `artifacts/reviews/review-issue-70.json` written; review `status` is `PASS`
- [x] Frontend: `npm test -- --testPathPattern=test_ui_only_home` passes
- [x] Frontend: PR Validation `lint-and-typecheck`, `test`, `frontend` jobs pass
- [x] Backend: N/A — web-only change
- [x] Migrations: N/A — no migration changes
- [x] `artifacts/validation/validation-issue-70.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `web/` MODULE.md | N/A — app shell, not a Tier 1/2 module |
| Handoff | N/A |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-70.json` |
| Validation | `artifacts/validation/validation-issue-70.json` |
