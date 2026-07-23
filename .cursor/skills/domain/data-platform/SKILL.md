---
name: data-platform-executor
description: >-
  Executor Agent domain skill for Postgres schema, migrations, repositories,
  and ETL consumer durability. Use when implementing persistence, Alembic, or
  ingest dedup — not vendor I/O or Juli /v1 product logic.
---

# Data Platform Executor

Schema, migrations, repos, ETL durability. TDD + artifact handoff:
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| Alembic migration, SQLAlchemy models | `postgres-patterns`, `performance.mdc` |
| Repository upsert / query | `python-patterns`, `postgres-patterns` |
| Supabase RLS | `supabase`, `supabase-postgres-best-practices` |
| ETL ingest / dedup | `services/etl/MODULE.md`, `data-sources.md` |
| Vendor fetch / webhook accept | **`integrations`** — not here |

## Owns / Does not own

**Owns:** ORM (`models/models.py`), Alembic (`database/migrations/versions/`),
repos (`repositories/repos.py`), ETL consumer dedup/persist/DLQ (`services/etl/`).

**Does not own:** **`integrations`** (vendor I/O + handoff bytes only),
**`backend`** (`/v1/*`, scoring, copy, Juli auth),
**`machine-learning`** (`backend/src/juli_backend/ai/`).

## Required context + load map

- [`data-sources.md`](../../../docs/architecture/data-sources.md), [`docs/api/data-models/`](../../../docs/api/data-models/)
- Migrations: root `alembic.ini` → `backend/src/juli_backend/database/migrations/`
- **Load map:** `SKILL.md` → `REFERENCE.md` → `postgres-patterns.md`, `python-testing.md`

## Juli recipes

**Migration** — one intent per revision; `env.py` + `Base.metadata`; reversible
`upgrade()`/`downgrade()`.

**Model** — `models/models.py`; register in `env.py` for autogenerate; index FK join cols.

**Repository** — `*Repo(session)` in `repositories/repos.py`; `NotFound` from
`database/exceptions.py`; ETL upserts handle `IntegrityError`.

**ETL consumer** — `EtlConsumer`: `ProcessedEventsRepo` dedup → transform → repo upsert → DLQ;
shop-scoped locks (`services/etl/consumer.py`).

Deeper patterns: [`REFERENCE.md`](REFERENCE.md).

## Domain test surfaces

- **Repo:** `session`/`engine` fixtures (`tests/unit/conftest.py`)
- **Migration:** round-trip `tests/integration/test_migrations.py` (Postgres when reachable)
- **ETL:** dedup + DLQ on public `EtlConsumer` entrypoints; no vendor HTTP

TDD + artifact: see `agent-runtime/docs/agent-runtime.md` (surfaces above only).

## Implementation artifact

```bash
python agent-runtime/scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain data-platform
```

## Review focus

Data-source legality, PII, reversibility, indexing, canonical entity consistency.

## Validation

`alembic upgrade head` → `downgrade -1` → `upgrade head`; migration integration tests; `ruff`, `mypy`.

## Must not

Forbidden sources (`data-sources.md`); vendor HTTP; Juli `/v1` product logic; ship or validate.
