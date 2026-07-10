---
name: data-platform-executor
description: >-
  Executor Agent domain skill for Postgres, migrations, ETL, and repository
  layers. Use when implementing schema changes, data ingestion, or persistence
  work.
---

# Data Platform Executor

Executor Agent domain skill for data and persistence. Implements with built-in
TDD (Red → Green → Refactor). Canonical requirements:
[`docs/architecture/agent-runtime.md`](../../../docs/architecture/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| Alembic migration, SQLAlchemy models | `postgres-patterns`, `performance.mdc` |
| Supabase RLS, auth integration | `supabase`, `supabase-postgres-best-practices` |
| ETL / ingestion handoff | `data-sources.md`, ordering/ETL `MODULE.md` |

## Required context

- [`docs/architecture/data-sources.md`](../../../docs/architecture/data-sources.md) — allowed sources for current phase
- [`docs/api/data-models/`](../../../docs/api/data-models/) — canonical entities
- Migration history under `alembic/versions/`
- Repository modules in `src/shared/utils/data/`

## TDD expectations

- **Red:** failing migration test, repo integration test, or data validation test
- **Green:** schema/repo change that passes
- **Refactor:** index/query cleanup; reversible migrations preserved

Cover migration up/down, idempotency for ETL paths, and entity consistency with
canonical schemas.

## Review focus

Data-source legality, PII constraints, schema reversibility, indexing/query
performance, consistency with canonical entities.

## Validation

Migration round-trip (`alembic upgrade head` → `downgrade -1` → `upgrade head`),
module drift checks, data-source policy where scripted.

## Implementation artifact (required handoff)

Before Review Agent, write `artifacts/implementations/implementation-issue-<n>.json`.

```bash
python scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain data-platform
```

Include migration paths in `filesModified`, migration/repo tests in `testsAdded`, and
data risks in `risks`. Note applicable `data-sources.md` rows in `assumptions`.

Schema: [`docs/schemas/agent-runtime/implementation-artifact.schema.json`](../../../docs/schemas/agent-runtime/implementation-artifact.schema.json)

## Must not

- Introduce forbidden data sources per `data-sources.md`
- Ship or validate — hand off to Review Agent
