# backend/src/juli_backend/services/aggregates

## Purpose

Rules-only SQL/Python feature aggregates over production-synced Postgres commerce
tables (`orders`, `products`, `returns`). Phase 2 Milestone A — no trained ML or model
artifact loading. Slice: `EXECUTION.md` P2-A3 (#300).

## Public API

- `build_feature_aggregates(session, shop_id, *, lifecycle)` → `FeatureAggregateSnapshot`
- `classify_shop_profile(signals)` → `NEW_SHOP` | `MID_LARGE_SHOP`
- `resolve_health_snapshot(...)` → tier-aware health fields per `endpoints.md`
- `SYNCED_DATA_SOURCES` — `frozenset({"orders", "products", "returns"})`

## Dependencies

- `juli_backend.repositories.repos` — `OrdersRepo`, `ProductsRepo`, `ReturnsRepo`
- `juli_backend.models.models` — `Shop` (shop age from `created_at`)

## Key Behaviors

- Aggregates query **only** synced commerce tables — no TikTok client, ETL ingest, or
  sandbox write paths
- `shop_profile` uses deterministic rules ported from
  `apps/dashboard/src/lib/operations/classification.ts` (reference only)
- `health_data_source: api | proxy | unavailable` — never fabricates SPS/VP/AHR when
  `unavailable`
- `ShopLifecycleContext` carries probation/health API fields not yet on `Shop` rows

## Out of scope

- T8 router / `juli_backend.ai.seller_stage` inference
- Materialized views / OLAP schema (future P2-B slices)
- Webhook or polling orchestration
