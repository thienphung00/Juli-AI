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
