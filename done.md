# Definition of Done — Issue #40

Checklist for `scripts/validate/check_done_md.py`.

## Required

- [x] Issue acceptance criteria each have a named pytest mapping in `artifacts/reviews/review-issue-40.json`
- [x] `python scripts/ci/generate_review_artifact.py --issue 40` written; review `status` is `PASS`
- [x] Backend: `ruff check .` passes on changed files; pre-existing repo warnings unchanged
- [x] Backend: `mypy src/alerts/channels/zalo.py` passes
- [x] Backend: `pytest tests/` passes (217 tests)
- [x] Migrations: N/A — no migration changes
- [x] Frontend (`web/`): N/A — alerts channel only
- [x] `artifacts/validation/validation-issue-40.json` exists with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | Status |
|------|--------|
| `src/alerts/MODULE.md` updated | Yes |
| Handoff `parallel-status.md` | In-flight row for #40 |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-40.json` |
| Validation | `artifacts/validation/validation-issue-40.json` |
