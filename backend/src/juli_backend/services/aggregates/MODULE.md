# backend/src/juli_backend/services/aggregates

## Purpose

Rules-only SQL/Python feature aggregates over production-synced Postgres commerce
tables (`orders`, `products`, `returns`, `order_items`, `inventory_items`).
Phase 2 Milestone A (#300) + computed KPI rollups (#374). No trained ML or model
artifact loading.

## Public API

- `build_feature_aggregates(session, shop_id, *, lifecycle, computed_at)` → `FeatureAggregateSnapshot`
- `compute_all_kpis(...)` → `ComputedKpiMetrics` (pure formulas in `computed_kpis.py`)
- `classify_shop_profile(signals)` → `NEW_SHOP` | `MID_LARGE_SHOP`
- `resolve_health_snapshot(...)` → tier-aware health fields per `endpoints.md`
- `SYNCED_DATA_SOURCES` — `frozenset({"orders", "products", "returns", "order_items", "inventory_items"})`
- `ORDER_DISPATCH_SLA_HOURS` — 48h dispatch SLA proxy (`thresholds.py`; cites `operational-limits.md` FDR/LDR)

## Dependencies

- `juli_backend.repositories.repos` — `OrdersRepo`, `ProductsRepo`, `ReturnsRepo`,
  `OrderItemsRepo`, `InventoryRepo`
- `juli_backend.models.models` — `Shop` (shop age from `created_at`)

## Key Behaviors

- Aggregates query **only** synced commerce tables — no TikTok client, ETL ingest, or
  sandbox write paths
- Multi-endpoint KPI formulas live in `computed_kpis.py`; `signals.py` applies
  thresholds and `visual_layer.md` one-liners only
- Division-by-zero and missing sync → metric `null` → advisory `unavailable`
- `shop_profile` uses deterministic rules ported from
  `apps/dashboard/src/lib/operations/classification.ts` (reference only)
- `health_data_source: api | proxy | unavailable` — never fabricates SPS/VP/AHR when
  `unavailable`
- `ShopLifecycleContext` carries probation/health API fields not yet on `Shop` rows

## Out of scope

- T8 router / `juli_backend.ai.seller_stage` inference
- Promotion API ETL for Ads KPIs (ROAS/CAC/CTR stay unavailable until separate slice)
- Materialized views / OLAP schema (future P2-B slices)
- Webhook or polling orchestration
