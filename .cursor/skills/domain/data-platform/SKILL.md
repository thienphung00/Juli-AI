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
repos (`repositories/`, one module per aggregate on `_base.py`), ETL consumer
dedup/persist/DLQ (`services/etl/`).

**Does not own:** **`integrations`** (vendor I/O + handoff bytes only),
**`backend`** (`/v1/*`, scoring, copy, Juli auth),
**`machine-learning`** (`backend/src/juli_backend/ai/`).

## Required context + load map

- [`data-sources.md`](../../../docs/architecture/data-sources.md), [`docs/api/data-models/`](../../../docs/api/data-models/)
- Migrations: root `alembic.ini` → `backend/src/juli_backend/database/migrations/`
- **Standard + exemplars:** [`docs/architecture/code-standard.md`](../../../docs/architecture/code-standard.md);
  [`repositories/MODULE.md`](../../../backend/src/juli_backend/repositories/MODULE.md) is the package map
- **Load map:** `SKILL.md` → `REFERENCE.md` → `postgres-patterns.md`, `python-testing.md`

## Juli recipes

**Migration** — one intent per revision; `env.py` + `Base.metadata`; reversible
`upgrade()`/`downgrade()`.

**Model** — `models/models.py`; register in `env.py` for autogenerate; index FK join cols.

**Repository** — extend `ShopScopedRepo` (`repositories/_base.py`): set `_model` and, for synced
entities, `_lookup_attrs`; build every query through `self._scoped(shop_id, ...)`; borrow the
session and never commit; `get` raises `NotFound`, `find`/`get_by_*` return `None`; naive UTC via
`utc_now_naive()`. `upsert` is inherited (stale-`update_time` guard + `IntegrityError` retry),
not rewritten. Exemplar: `repositories/commerce.py`.

**ETL consumer** — `EtlConsumer`: `ProcessedEventsRepo` dedup → transform → repo upsert → DLQ;
shop-scoped locks (`services/etl/consumer.py`).

Deeper patterns: [`REFERENCE.md`](REFERENCE.md).

## Domain test surfaces

- **Repo:** `session` fixture + rows from `tests/support/builders` (`make_tenant`, `make_order`, …);
  exemplar `tests/unit/test_repositories_base.py`, `tests/unit/test_repositories_commerce.py`
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
