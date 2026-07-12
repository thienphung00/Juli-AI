# Scope Alignment — Issue #365 (child of parent #278)

**Parent issue:** #278 (constant — `parent-cache-issue-278.json`)  
**Status:** valid  
**Cache block version:** 1  
**Last validated:** 2026-07-12  
**Companion artifact:** `agent-runtime/artifacts/workflow-cache/issue-context-cache-365.json`

## Authority chain (this run)

| Rank | Source | Applies because |
|------|--------|---------------|
| 1 | `EXECUTION.md` slice P2-A2 | Phase/slice law — canonical entities + migrations |
| 2 | `parent-cache-issue-278` | Epic constant for all children |
| 3 | GitHub issue #365 | **Child** acceptance criteria (unique) |
| 4 | `docs/handoffs/phase-2-tiktok-implementation.md` | Epic handoff (when not superseded) |

## In scope (this issue)

- Alembic migration integration tests under `tests/integration/test_migrations.py`
- Seeded row survival across `downgrade -1` / `upgrade head`
- Constraint integrity checks after migration round trip
- Contract tests for CI Postgres wiring and DATABASE_URL usage

## Out of scope

- New migrations or schema changes
- Supabase pooler/local `.env` connectivity (tests skip when Postgres unreachable)
- `web/`, `ios/`, `src/modules/ml/`

## Acceptance criteria (GitHub #365)

1. New test file lives in `tests/integration/test_migrations.py`
2. Test runs in the CI `test` job (Postgres service via `DATABASE_URL`)
3. Test fails if a migration drops data, breaks foreign keys, or removes required constraints
4. Uses the same Postgres connection pattern as other integration tests (env `DATABASE_URL`)
5. One behavior per test where practical (downgrade data survival vs constraint integrity)
