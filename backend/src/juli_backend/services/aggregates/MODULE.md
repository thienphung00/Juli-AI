# backend/src/juli_backend/services/aggregates

## Purpose

Rules-only SQL/Python feature aggregates over production-synced Postgres commerce
tables (`orders`, `products`, `returns`, `order_items`, `inventory_items`) plus
analytics ETL outputs (`analytics_performance_intervals`, `tiktok_sync_state` for
A-25 promotion partition). Phase 2 Milestone A (#300) + computed KPI rollups (#374)
+ analytics-backed fields (#426). No trained ML or model artifact loading.

## Public API

- `build_feature_aggregates(session, shop_id, *, lifecycle, computed_at)` → `FeatureAggregateSnapshot`
- `compute_all_kpis(...)` → `ComputedKpiMetrics` (pure formulas in `computed_kpis.py`)
- `compute_analytics_kpis(...)` — analytics grain rollups from ETL intervals (#426)
- `classify_shop_profile(signals)` → `NEW_SHOP` | `MID_LARGE_SHOP`
- `resolve_health_snapshot(...)` → tier-aware health fields per `endpoints.md`
- `SYNCED_DATA_SOURCES` — commerce + analytics Postgres tables listed above
- `ORDER_DISPATCH_SLA_HOURS` — 48h dispatch SLA proxy (`thresholds.py`; cites `operational-limits.md` FDR/LDR)

## Dependencies

- `juli_backend.repositories.repos` — `OrdersRepo`, `ProductsRepo`, `ReturnsRepo`,
  `OrderItemsRepo`, `InventoryRepo`, `AnalyticsPerformanceRepo`, `TikTokSyncStateRepo`
- `juli_backend.models.models` — `Shop` (shop age from `created_at`),
  `AnalyticsPerformanceInterval`

## Key Behaviors

- Aggregates query synced commerce and analytics Postgres tables — no TikTok client,
  ETL ingest, or sandbox write paths
- Multi-endpoint KPI formulas live in `computed_kpis.py`; `signals.py` applies
  thresholds and `visual_layer.md` one-liners only
- Analytics partition missing → analytics KPI fields stay `null` (no zero fabrication)
- A-36 shop traffic conversion from shop-grain `conversion_rate`; A-34/A-32 GMV + CTR
  rollups from product/sku grains; A-25 promotion watermark joins revenue denominator
- Division-by-zero and missing sync → metric `null` → advisory `unavailable`
- `shop_profile` uses deterministic rules ported from
  `apps/dashboard/src/lib/operations/classification.ts` (reference only)
- `health_data_source: api | proxy | unavailable` — never fabricates SPS/VP/AHR when
  `unavailable`
- `ShopLifecycleContext` carries probation/health API fields not yet on `Shop` rows

## Out of scope

- T8 router / `juli_backend.ai.seller_stage` inference
- Promotion spend persistence (ROAS/CAC spend denominator stays null until ETL slice)
- Materialized views / OLAP schema (future P2-B slices)
- Webhook or polling orchestration
