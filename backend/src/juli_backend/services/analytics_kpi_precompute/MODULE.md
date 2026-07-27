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
- ``build_product_funnel_kpi(intervals)`` → ``KpiEnvelopeEntry`` — product-grain GMV
  by day (A-34); wired as ``kpis.product_funnel``
- ``build_live_performance_kpi(intervals)`` → ``KpiEnvelopeEntry`` — shop-grain LIVE
  rollup rows only (A-28/A-29); wired as ``kpis.live_performance``

## Payload contract

- KPI key ``gmv_tiktok`` with label ``GMV (TikTok)`` — never ``net_revenue``
- KPI key ``product_funnel`` with label ``Product funnel (GMV)`` (A-34)
- KPI key ``live_performance`` with label ``LIVE performance (GMV)`` (A-28/A-29)
- ``availability``: ``available`` when sourced rows exist; ``unavailable`` otherwise
- ``series``: ``[{t, v}]`` when available; omitted when unavailable (no fabrication)
- ``meta.source_partitions``: includes ``A-36`` / ``A-34`` / ``A-28``+``A-29`` only when
  the corresponding KPI is available
- Inventory/Ops/CSAT keys are **not** wired — no daily series builders exist; omit or
  leave unavailable rather than fabricate points

## Dependencies

- ``AnalyticsKpiEnvelopesRepo`` (#525) — idempotent upsert on ``(shop_id, kind)``
- ``AnalyticsPerformanceInterval`` — warm rows from backfill (#466)

## JSONB merge

Assign a **new** payload dict when merging KPI keys (SQLAlchemy JSONB mutation caveat);
see ``context7-sqlalchemy-jsonb-526-527.txt``.
