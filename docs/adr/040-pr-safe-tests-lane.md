# ADR-040: PR-safe Tests lane (markers, timeouts, live on merge_group)

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-003](003-ai-native-cicd-policy.md) (artifact-driven CI; two-tier PR / merge_group).  
**Does not change:** ADR-003 artifact gates (`validate-artifacts`, review/validation JSON); coverage floor policy of `--cov-fail-under=80` on product pytest.

## Context

The GitHub Actions `test` job ran `pytest tests/` whenever the `backend` path filter matched. That single lane mixed:

- Fast unit and mocked integration tests
- Live TikTok Partner / sandbox HTTP (when CI secrets are present)
- Demo deploy/exit-gate contract pytest already owned by `demo-deploy-contracts` / `demo-e2e`

Recent PRs showed “stuck” Tests UX: healthy runs finish in ~4–5 minutes, but long Pytest steps were often **cancelled by concurrency** after ~20 minutes on a new push. There was no `pytest-timeout`, and live Partner calls shared the critical PR path with deterministic coverage.

## Decision

1. **PR-safe Tests** is the default PR `test` job: unit + non-live integration only.
2. Pytest markers (registered in `backend/pyproject.toml`):
   - **`live`** — real outbound TikTok Partner / sandbox HTTP (e.g. oauth exchange/refresh). Local ASGI webhook tests that only use sandbox secrets for HMAC signing are **not** `live`.
   - **`demo_contract`** — Demo deploy/exit-gate contract pytest owned by dedicated demo CI jobs.
3. PR `test` runs with `-m "not live and not demo_contract"`, **`pytest-timeout` 30s per test**, and a **15-minute** Actions job timeout. Keep `--cov=juli_backend --cov-fail-under=80`.
4. **`live`** tests run in a **separate merge_group-only** job (not on every PR push).
5. **`demo_contract`** tests are excluded from the main `test` job; dedicated demo jobs remain SoT.
6. Suite lean-out (delete/merge shallow overlapping tests) follows this wiring; it does not reopen the lane policy above.
7. **`migration_heavy`**: seeded Alembic round-trips (`test_migrations.py`) run on merge_group and on PRs that touch migration paths; excluded from default PR-safe Tests. `migration-check` remains the fast structural gate.
8. **`phase_scaffold`**: Phase 2.5 deploy/doc contracts run on merge_group only (not every backend PR).

## Consequences

- PR feedback becomes deterministic and bounded; live Partner flakiness no longer blocks every backend PR.
- New live, demo-contract, migration_heavy, or phase_scaffold tests must carry the correct marker or they will incorrectly run (or incorrectly skip) on PR-safe Tests.
- Merge Queue remains the full/near-full gate for live Partner, migration_heavy, and phase_scaffold coverage.
- Glossary: `CONTEXT.md` § CI / test lanes.
