# Module: data

## Responsibility
Defines the persistence layer: SQLAlchemy async models, repository abstractions,
database session management, and Alembic migrations for the Juli-AI platform.

## Public Interface

### Models — Auth / Core
- `User` — SQLAlchemy model for authenticated sellers
- `Shop` — SQLAlchemy model for TikTok Shop entities, scoped by user
- `TikTokCredential` — SQLAlchemy model for encrypted OAuth tokens per shop

### Models — Commerce (#28)
- `Order` — orders synced from TikTok, indexed on `(shop_id, created_at)`
- `Product` — products synced from TikTok, indexed on `(shop_id, created_at)`
- `InventoryItem` — SKU-level inventory, indexed on `(shop_id, created_at)`
- `Settlement` — settlements with `status` defaulting to `"pending"` (7-14 day confirmation window); `update_time` is the reconciliation key

### Models — ETL (#32)
- `ProcessedEvent` — ETL ingest idempotency ledger keyed by `event_id`

### Repositories — ETL (#32)
- `ProcessedEventsRepo(session).claim(event_id, shop_id) -> bool` — returns False if already seen

### Models — Analytics (#28)
- `Creator` — affiliate creators per shop
- `Livestream` — post-stream summaries, FK to `Creator`
- `AlertConfig` — per-shop alert rules (`threshold_json` for per-type thresholds)
- `AlertHistory` — fired alert log, FK to `AlertConfig`
- `Recommendation` — system-generated recommendations

### Models — Commerce graph (P1-1 / Issue #92)
- `Campaign` — collaboration node linking creator + shop with predicted/realized metrics
- `GraphEdge` — relationship edges (`has_sold`, `potential_match`, `trust_score`, `predicted_vs_actual`, …)

### Repositories — Commerce graph (P1-1)
- `GraphRepo(session).upsert_edge(shop_id, …) -> GraphEdge` — idempotent on natural key
- `GraphRepo(session).list_edges(shop_id, edge_type?, node_type?, node_id?) -> list[GraphEdge]`
- `GraphRepo(session).create_campaign(shop_id, creator_id, product_ids, …) -> Campaign`
- `GraphRepo(session).find_campaign_by_idempotency(shop_id, idempotency_key) -> Campaign | None`
- `GraphRepo(session).get_campaign(shop_id, campaign_id) -> Campaign | None`

### Repositories — Auth / Core
- `UsersRepo(session).get(user_id) -> User` — returns user or raises `NotFound`
- `ShopsRepo(session).list(user_id) -> list[Shop]` — returns shops belonging to user
- `ShopsRepo(session).create(user_id, **kwargs) -> Shop` — creates a shop for user
- `ShopsRepo(session).get_by_tiktok_id(tiktok_shop_id) -> Shop | None` — find by TikTok ID
- `TikTokCredentialRepo(session).create(shop_id, ...) -> TikTokCredential`
- `TikTokCredentialRepo(session).get_by_shop(shop_id) -> TikTokCredential`
- `TikTokCredentialRepo(session).update_tokens(credential_id, ...) -> TikTokCredential`

### Repositories — Commerce & Analytics (#28)
- `ShopScopedRepo[T]` — generic base with mandatory `shop_id` scoping
- `ShopScopedRepo.list(shop_id, *, limit=50, after=None) -> list[T]` — keyset (cursor) pagination
- `ShopScopedRepo.get(shop_id, entity_id) -> T` — raises `NotFound` on miss or wrong shop
- `ShopScopedRepo.upsert(*, shop_id, **kwargs) -> T` — idempotent write via `_lookup_attr` + `update_time` dedup
- Concrete repos: `OrdersRepo`, `ProductsRepo`, `InventoryRepo`, `SettlementsRepo`, `CreatorsRepo`, `LivestreamsRepo`
- `AlertConfigsRepo` — `.create()`, `.get_by_type()`, `.list_active()`
- `AlertHistoryRepo` — `.create()`, `.has_recent_for_type()` (cooldown dedup)
- CRUD-only: `RecommendationsRepo` (add `.create()`)

### Models — Analytics backfill (P2-9-2 / Issue #464)
- `AnalyticsBackfillPartition` — durable `(shop_id, bucket, date)` backfill progress

### Repositories — Analytics backfill (P2-9-2)
- `AnalyticsBackfillPartitionsRepo(session).mark_complete(shop_id, bucket, date)` — idempotent complete marker
- `AnalyticsBackfillPartitionsRepo(session).mark_failed(shop_id, bucket, date, error, retryable=True)` — records retryable failure with redacted `last_error`
- `AnalyticsBackfillPartitionsRepo(session).list_incomplete(shop_id, bucket, start, end) -> list[AnalyticsBackfillPartition]` — pending/failed partitions in range
- `AnalyticsBackfillPartitionsRepo(session).is_complete(shop_id, bucket, date) -> bool`

### Infrastructure
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
- code: src/data/
