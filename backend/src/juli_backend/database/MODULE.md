# Module: database

## Responsibility
Defines the persistence layer: SQLAlchemy async models, repository abstractions,
database session management, and Alembic migrations for the Juli-AI platform.

## Public Interface

Import from the package root only:

```python
from juli_backend.database import Shop, ShopsRepo, get_session, ...
```

Deep imports of ``models.models``, ``repositories.repos``, and
``services.etl.persistence.ingest`` are internal unless re-exported below.

### Package facade (`__init__.py`)

Matches ``__all__``. Model and repository symbols resolve lazily (PEP 562
``__getattr__``) to avoid import cycles. ``Base``, ``NotFound``, ``get_session``,
and ``init_session_factory`` are eager exports.

**Models**
- `ActionCard`, `AlertConfig`, `AlertHistory`, `Campaign`, `Creator`, `GraphEdge`
- `InventoryItem`, `Livestream`, `Order`, `ProcessedEvent`, `Product`, `Recommendation`
- `Settlement`, `Shop`, `TikTokCredential`, `User`

**Repositories**
- `ActionCardsRepo`, `AlertConfigsRepo`, `AlertHistoryRepo`, `CreatorsRepo`, `GraphRepo`
- `InventoryRepo`, `LivestreamsRepo`, `OrdersRepo`, `ProcessedEventsRepo`, `ProductsRepo`
- `RecommendationsRepo`, `SettlementsRepo`, `ShopScopedRepo`, `ShopsRepo`
- `TikTokCredentialRepo`, `UsersRepo`

**Infrastructure**
- `Base` — declarative base for all models
- `NotFound` — raised when a requested entity does not exist
- `get_session() -> AsyncIterator[AsyncSession]` — FastAPI dependency yielding a DB session
- `init_session_factory(factory)` — configures the global session factory at app startup

## Dependencies
- `sqlalchemy[asyncio]` — async ORM
- `asyncpg` — PostgreSQL async driver (production)
- `psycopg2-binary` — PostgreSQL sync driver for Alembic migrations
- `aiosqlite` — SQLite async driver (testing)
- `alembic` — schema migrations

### Medallion schemas (Phase 3.5-A0 / ADR-046)
- Four Postgres schemas: `bronze.*` (append-only raw), `silver.*` (idempotent domain upserts), `gold.*` (serving + ML stub), `ops.*` (pipeline checkpoints)
- **ML feature source of truth:** `silver.*` only — training and inference read silver domain rows, never serving `gold.kpi_envelopes`; optional `gold.ml_feature_snapshots` is an acceleration stub (#603)
- **Serving gold SoT:** `gold.kpi_envelopes` — PK `shop_id`, flexible `payload.kpis` jsonb (#606); legacy `public.analytics_kpi_envelopes` is read-only with compat view `analytics_kpi_envelopes_compat`
- **Silver domain SoT:** `silver.orders` / `silver.returns` — natural keys `(shop_id, tiktok_order_id)` / `(shop_id, tiktok_return_id)` (#607); legacy `public.orders` / `public.returns` are read-only after cutover
- Grant isolation: `bronze`, `silver`, and `ops` are blocked from `anon` / `authenticated` PostgREST roles; `gold.kpi_envelopes` is client-readable with RLS

### One-writer ownership map (post-cutover — ADR-046 / #608)

After silver (#607) and gold (#606) cutovers, **one module owns writes** per medallion
table. Readers may be many; writers must not drift. Enforced by
`agent-runtime/scripts/ci/medallion_one_writer.py` and
`tests/unit/test_medallion_one_writer_ownership.py`.

| Layer / table | Owning module | Writer repos / entrypoints | Readers |
|---------------|---------------|----------------------------|---------|
| Bronze raw append (`bronze.order_raw_payloads`, `bronze.return_raw_payloads`) | **Ingest / ETL bronze writer** | `BronzeOrderRawPayloadsRepo.append_batch`, `BronzeReturnRawPayloadsRepo.append_batch` under `services/etl/` | Silver promotion only |
| `silver.orders` / `silver.returns` | **Domain silver upsert service** | `OrdersRepo.upsert`, `ReturnsRepo.upsert` via `services/etl/consumer.py` and `services/etl/silver_promotion.py` (`SilverOrdersReturnsPromoter`) | Gold compute, ML (future) |
| `gold.kpi_envelopes` | **Shared Compute gold writer** (A1; A0 seeds shell) | `GoldKpiEnvelopesRepo.upsert` / `AnalyticsKpiEnvelopesRepo.upsert` via `services/gold_kpi_envelope_serving.py` (A0 shell) and `services/analytics_kpi_precompute/` (transitional until A1 consolidates) | Demo/API, Redis read-through (A1), Decisions (#599) |
| `ops.analytics_backfill_partitions` | **Backfill / batch partition repo** | `AnalyticsBackfillPartitionsRepo.mark_complete` / `mark_failed` under `services/analytics_backfill/` | A2 scheduler |
| `gold.ml_feature_snapshots` | **Stub / empty OK** (#603) | No writer required for A0 exit; ML reads **silver** only | None required for A0 |

**Notes**

- `public.webhook_raw_events` remains a **read-only audit shim**; forward domain raw
  landing is bronze append only (#605).
- Product lifecycle mutations on `silver.orders` (e.g. `OrdersRepo.confirm_shipment`
  from `/v1/orders`) are seller actions outside ingest reconciliation — not a second
  medallion ingest writer.
- Do **not** add parallel writers during cutover windows; retire legacy writers after
  bounded dual-write (ADR-046).

### Shared Compute Orchestrator job boundary (Q4 — A1 hooks)

Locked in [ADR-046 Q4](../../../../docs/adr/046-cdp-medallion-physical-model.md). **A0
documents only** — no deployed material webhook enqueue or full orchestrator runtime in
this slice (#608). **A1 Speed (#601)** wires the shop-scoped job.

**Principle:** One **shop-scoped Shared Compute job** per **material trigger** (webhook,
targeted fetch completion, reconcile window, or scheduled refresh). Each job runs the full
medallion chain in idempotent stages — no partial gold writes without silver promotion.

| Stage | Action | Idempotency |
|-------|--------|-------------|
| 1 — Bronze | Append raw webhook/fetch payloads to `bronze.*` | Append-only; dedupe keys at silver |
| 2 — Silver | Upsert normalized domain rows (`silver.*`) via `SilverOrdersReturnsPromoter` | One canonical row per domain key |
| 3 — Gold | Write / refresh `gold.kpi_envelopes` (Decisions inputs when #599 wires) | Full envelope rewrite or keyed upsert per shop |

**One job owns all three stages** for a given `(shop_id, trigger)` — not separate cron MV
refreshes or per-table gold writers. Cross-shop batching, visitor-triggered runs on Mock
Demo reads, and gold→silver reverse writes are **out of scope** (ADR-046 Q4).

See also [`services/etl/MODULE.md`](../services/etl/MODULE.md) for ingest-side bronze/silver
entrypoints.

## Invariants
- All repo queries are scoped by `user_id` (auth repos) or `shop_id` (commerce/analytics repos) — no cross-tenant data leakage
- `UsersRepo.get()` raises `NotFound` rather than returning `None`
- `ShopScopedRepo.get()` raises `NotFound` when entity belongs to a different shop
- `ShopScopedRepo.upsert()` rejects stale data: updates only when incoming `update_time` > existing
- Settlement `status` defaults to `"pending"` — confirmed only after 7-14 day window
- Models use UUID primary keys, not auto-increment integers
- `created_at` / `updated_at` timestamps are server-managed
- Commerce models carry `update_time` as the reconciliation key (not insertion order)

## Owners
- domain: data
- code: backend/src/juli_backend/database/
