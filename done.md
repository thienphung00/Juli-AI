# Definition of Done — Issue #36

Skill chain: `review` → `validate` → `ship` ([ADR-003](docs/decisions/003-ai-native-cicd-policy.md)).

## Required

- [x] Issue acceptance criteria each have a named pytest mapping in `artifacts/reviews/review-issue-36.json`
- [x] `artifacts/reviews/review-issue-36.json` written; review `status` is `PASS`
- [x] Backend: `pytest tests/` passes (198 tests)
- [x] Migrations: `alembic/versions/003_alert_config_threshold.py` added
- [x] `artifacts/validation/validation-issue-36.json` with `status: "PASS"`
- [x] No secrets, tokens, or credentials committed

## Conditional

- [x] `MODULE.md` for `src/alerts` and updated `src/data`
- [x] Row added to `docs/architecture/map.md`
