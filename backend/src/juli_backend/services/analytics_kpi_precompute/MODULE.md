# backend/src/juli_backend/services/analytics_kpi_precompute

## Purpose

Phase 2.10 Analytics KPI precompute — reads warm `analytics_performance_intervals`
rows and upserts shop-scoped JSON envelopes in `analytics_kpi_envelopes` (ADR-038).

## Public API

- ``precompute_shop_analytics_kpis(session, shop_id, *, computed_at=None)``
  → ``AnalyticsKpiEnvelope`` — orchestrator; merges KPI slices into ``kind="analytics"``
  envelope and upserts via ``AnalyticsKpiEnvelopesRepo``
- ``build_gmv_tiktok_kpi(session, shop_id)`` → ``dict`` — ``kpis.gmv_tiktok`` slice
  from shop-grain intervals with non-null GMV (A-36 revenue partition)

## Payload contract

- KPI key ``gmv_tiktok`` with label ``GMV (TikTok)`` — never ``net_revenue``
- ``availability``: ``available`` when shop-grain GMV rows exist; ``unavailable`` otherwise
- ``series``: ``[{t, v}]`` from ``start_date`` + ``gmv`` when available

## Dependencies

- ``AnalyticsKpiEnvelopesRepo`` (#525) — idempotent upsert on ``(shop_id, kind)``
- ``AnalyticsPerformanceInterval`` — shop-grain warm rows from backfill (#466)
