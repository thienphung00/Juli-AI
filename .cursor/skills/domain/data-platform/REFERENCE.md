# Data platform reference (schema, repos, ETL)

Curated patterns for the 80% path. For library API details and churn-prone behavior,
use the **Context7 CLI** at Executor time when Focus/Meta selects it (see **Sources /
live Context7 pointers**). Load on demand — not always injected in full.

---

## 1. Alembic layout and revision workflow

- **Config:** repo-root `alembic.ini` → `script_location = backend/src/juli_backend/database/migrations`
- **Env:** `database/migrations/env.py` sets `target_metadata = Base.metadata`, imports models
  for autogenerate registration, resolves URL via `sync_database_url()`.
- **Revisions:** `database/migrations/versions/<nnn>_<slug>.py` — one intent per file.

Context7 extract (`/websites/alembic_sqlalchemy` — autogenerate + downgrade):

```bash
alembic revision --autogenerate -m "describe intent"
# Review upgrade()/downgrade(); never ship unchecked autogen for prod tables
```

```python
def upgrade():
    op.add_column("account", sa.Column("last_transaction_date", sa.DateTime))

def downgrade():
    op.drop_column("account", "last_transaction_date")
```

**Validation:** `tests/integration/test_migrations.py` — upgrade → downgrade → upgrade with
seeded row assertions when Postgres `DATABASE_URL` is reachable.

---

## 2. SQLAlchemy 2.0 async session

Context7 extract (`/sqlalchemy/sqlalchemy` — AsyncSession):

```python
engine = create_async_engine(database_url)
factory = async_sessionmaker(engine, expire_on_commit=False)

async with factory() as session:
    async with session.begin():
        session.add_all([...])
```

Repo conventions in this codebase:

- **`get_session`** dependency yields session per request (`expire_on_commit=False`).
- **Tests:** in-memory SQLite via `tests/unit/conftest.py` (`engine`, `session` fixtures).
- **Queries:** prefer `select()` + `await session.execute()`; use `selectinload` for bounded eager loads.

---

## 3. Repository patterns

Location: `backend/src/juli_backend/repositories/repos.py`.

- Constructor takes `AsyncSession`; one repo class per aggregate/table family.
- **`get`** raises `database.exceptions.NotFound` — callers map to HTTP 404/401 at API layer.
- **Upsert paths** (ETL): catch `IntegrityError`, merge or re-fetch; keep shop-scoped keys.
- **Token fields:** use `database/token_crypto.py` encrypt/decrypt helpers — never store plaintext.

Add repo methods before wiring new ETL channels or `/v1` list endpoints that need new queries.

---

## 4. ETL consumer durability

Location: `services/etl/consumer.py` — `EtlConsumer`.

Flow:

1. Extract stable `event_id` (`services/etl/event_id.py`)
2. Dedup via `ProcessedEventsRepo` (duplicate → idempotent skip)
3. Transform per channel (`services/etl/transform.py`)
4. Upsert through domain repos (`OrdersRepo`, `ProductsRepo`, …)
5. On hard failure → DLQ handoff (`services/etl/channels.py:DLQ_CHANNEL`)

Operational constraints:

- Shop-scoped asyncio locks + `max_pending_per_shop` backpressure
- `latency_budget_seconds` — fail to DLQ rather than block ingest indefinitely
- Integrations hand off raw bytes; consumer owns durable writes only

---

## 5. Postgres indexing, RLS, and migrations safety

Prefer repo patterns in `domain/testing-patterns/postgres-patterns.md`:

- Composite indexes: equality columns first, then range; partial indexes for active rows.
- Keyset pagination over `OFFSET` on large tables.
- Additive migrations first; batch backfills; avoid long locks.

**Supabase / RLS:** when policies touch auth tables, also load Supabase agent skill
(`supabase-postgres-best-practices`) — RLS belongs in migration + policy review, not app routes.

Context7 (optional, index-adjacent):

```bash
npx ctx7@latest docs /sqlalchemy/sqlalchemy "Index create composite partial"
```

---

## 6. Juli path cheat-sheet

| Concern | Module(s) |
|---------|-------------|
| ORM models | `models/models.py`, `orm_base.py` |
| Async engine/session | `database/database.py` |
| Alembic env + versions | `database/migrations/` (via root `alembic.ini`) |
| Repositories | `repositories/repos.py` |
| ETL ingest | `services/etl/` (`consumer.py`, `transform.py`, `record.py`) |
| Canonical entities | `docs/api/data-models/` |
| Allowed sources | `docs/architecture/data-sources.md` |
| Vendor fetch (defer to `integrations`) | `integrations/tiktok/`, `services/analytics_backfill/` |

---

## 7. Sources / live Context7 pointers

This workspace uses the **Context7 CLI** (`npx ctx7@latest`), not Context7 MCP.

```bash
npx ctx7@latest library sqlalchemy "async session AsyncSession 2.0"
npx ctx7@latest docs /sqlalchemy/sqlalchemy "async_sessionmaker create_async_engine"
npx ctx7@latest docs /websites/alembic_sqlalchemy "revision autogenerate downgrade upgrade"
```

| Topic | Suggested CLI queries |
|-------|----------------------|
| Async ORM session | `docs /sqlalchemy/sqlalchemy` — `AsyncSession`, `async_sessionmaker`, `begin()` |
| Migrations | `docs /websites/alembic_sqlalchemy` — autogenerate review, `op.add_column`, downgrade |
| Indexes | `docs /sqlalchemy/sqlalchemy` — `Index`, composite/partial patterns |
| Supabase RLS | Supabase skill + `docs` for policy syntax when migration adds RLS |

**Example library IDs:** `/sqlalchemy/sqlalchemy`, `/websites/alembic_sqlalchemy`
(or `/sqlalchemy/alembic` — resolve with `library alembic`).

See [`.cursor/rules/context7-cli.mdc`](../../../rules/context7-cli.mdc).

**Repo authority:** `services/etl/MODULE.md`,
[`data-sources.md`](../../../docs/architecture/data-sources.md),
[ADR-031](../../../docs/adr/031-integrations-executor-domain.md),
[`postgres-patterns.md`](../testing-patterns/postgres-patterns.md).
