# Definition of Done

Checklist consumed by `scripts/validate/check_done_md.py` and the `validate` skill.
Complete every **Required** item before running `validate` or opening a merge-ready PR.

Skill chain: `review` → `validate` → `ship` ([ADR-003](docs/decisions/003-ai-native-cicd-policy.md)).

## Required

- [x] Issue acceptance criteria each have a named pytest mapping in `artifacts/reviews/review-issue-<n>.json`
- [x] `python scripts/ci/generate_review_artifact.py --issue <n>` written; review `status` is `PASS` (not `FAIL`)
- [x] Backend: `ruff check .` passes
- [x] Backend: `mypy src/` passes
- [x] Backend: `pytest tests/` passes
- [x] Migrations: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` passes (when migrations changed)
- [x] Frontend (`web/`): `npm run lint`, `npm run type-check`, and `npm run test` pass (when `web/` changed)
- [x] `artifacts/validation/validation-issue-<n>.json` exists with `status: "PASS"` (from `validate` skill or CI)
- [x] No secrets, tokens, or credentials committed

## Conditional

| Item | When required |
|------|----------------|
| `MODULE.md` updated for touched Tier 1/2 modules | Public interfaces changed in `src/` |
| Row added to `docs/architecture/map.md` | New module introduced |
| ADR at `docs/decisions/NNN-slug.md` | Architectural change (new module, breaking interface, policy change) |
| Handoff `docs/handoffs/<topic>-NN.md` updated | Work spans sessions or parallel agents |
| Rollback steps documented in PR body | Migrations, feature flags, or production-impacting change |

## Artifacts

| Artifact | Path |
|----------|------|
| Review | `artifacts/reviews/review-issue-32.json` |
| Validation | `artifacts/validation/validation-issue-32.json` |
| Release | `artifacts/releases/release-<version>.json` (after merge to `main`) |
