# Definition of Done — Issue #43

Checklist for `scripts/validate/check_done_md.py`.

## Required

- [x] Issue acceptance criteria each have a named pytest mapping in `artifacts/reviews/review-issue-43.json`
- [x] `python scripts/ci/generate_review_artifact.py --issue 43` written; review `status` is `PASS`
- [x] Backend: `ruff check .` passes
- [x] Backend: `mypy src/` passes (2 pre-existing errors in etl/, unchanged by this PR)
- [x] Backend: `pytest tests/` passes (215 tests)
- [x] Migrations: N/A — no migration changes
- [x] Frontend (`web/`): N/A — API-only slice
- [x] `artifacts/validation/validation-issue-43.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `src/api/MODULE.md` updated | Yes |
| Handoff `parallel-status.md` | In-flight row for #43 |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-43.json` |
| Validation | `artifacts/validation/validation-issue-43.json` |
