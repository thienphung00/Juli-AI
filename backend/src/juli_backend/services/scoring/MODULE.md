# backend/src/juli_backend/services/scoring

## Purpose

Rules-based daily batch scoring: feature aggregates → **visual_layer** advisory
signals → ranked **execution_layer** workflow recommendations. Slice:
`EXECUTION.md` P2-B1 (#303). No trained ML.

## Public API

- `run_daily_scoring_for_shop(session, shop_id, *, lifecycle, computed_at)` → `DailyScoringResult`
- `run_daily_scoring_batch(session, *, shop_ids, lifecycle_for_shop, computed_at)` → `list[DailyScoringResult]`
- `compute_scoring_signals(snapshot, *, lifecycle, computed_at, products)` → `ScoringSignals`
- `rank_workflow_recommendations(profile, signals)` → `WorkflowRecommendations`
- `format_advisory_one_line(change, signal_type, action)` — visual_layer one-line format
- `DAILY_SCORING_UTC_HOUR` / `DAILY_SCORING_CRON_UTC` — 08:00 UTC per `phase-2-mvp.md`

## Signal contract

Authoritative: [`docs/ml/visual_layer.md`](../../../../docs/ml/visual_layer.md).

Each KPI emits an `AdvisorySignal`:

- **change_text** → **risk|opportunity** → **action_hint** (`one_line` field)
- Six domains: shop_status, revenue, ads, inventory, operations, customer_service
- Phase 2: T3 policy rules (SPS/AHR/VP) + deterministic proxies from synced Postgres
- Shop Status KPIs render mock/fixture advisory only — **no workflow_keys** until Partner API fields exist
- KPIs without ETL fields emit `signal_type: unavailable` (never fabricated)

## Recommendations

Workflow keys align with [`webhook_catalog.py`](../tiktok/webhook_catalog.py) /
[`execution_layer.md`](../../../../docs/product/execution_layer.md) — **not** the
retired P1.8 six-workflow catalog.

## Dependencies

- `juli_backend.services.aggregates` — `build_feature_aggregates` (#300)
- `juli_backend.repositories.repos.ProductsRepo` — SKU ranking proxy (T7)

## Out of scope

- P1.8 `health_check_results` as backend signal authority
- Rules-based copy layer, Celery beat, Redis persistence
- Trained T1–T8 inference
