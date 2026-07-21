# backend/src/juli_backend/services/scoring

## Purpose

Rules-based daily batch scoring: feature aggregates → **visual_layer** advisory
signals → ranked **execution_layer** workflow recommendations → **rules-based copy**
(#303, #304). No trained ML. No cloud LLM.

## Public API

- `run_daily_scoring_for_shop(session, shop_id, *, lifecycle, computed_at)` → `DailyScoringResult`
- `run_daily_scoring_batch(session, *, shop_ids, lifecycle_for_shop, computed_at)` → `list[DailyScoringResult]`
- `compute_scoring_signals(snapshot, *, lifecycle, computed_at, products)` → `ScoringSignals`
- `rank_workflow_recommendations(profile, signals)` → `WorkflowRecommendations`
- `build_workflow_reasoning_copy(recommendation, signals)` → `WorkflowReasoningCopy` (#304)
- `build_reasoning_for_recommendations(recommendations, signals)` → `tuple[WorkflowReasoningSummary, ...]`
- `format_advisory_one_line(change, signal_type, action)` — visual_layer one-line format
- `DAILY_SCORING_UTC_HOUR` / `DAILY_SCORING_CRON_UTC` — 08:00 UTC per `phase-2-mvp.md`

## Signal contract

Authoritative: [`docs/ml/visual_layer.md`](../../../../docs/ml/visual_layer.md).

Each KPI emits an `AdvisorySignal`:

- **change_text** → **risk|opportunity** → **action_hint** (`one_line` field)
- Six domains: shop_status, revenue, ads, inventory, operations, customer_service
- Phase 2: T3 policy rules (SPS/AHR/VP) + deterministic proxies from synced Postgres
- Shop Status KPIs render mock/fixture advisory only — **no workflow_keys** until Partner API fields exist
- Ads CTR from analytics product-grain CTR rollup (#428); ROAS/CAC stay `unavailable` until promotion spend ETL
- KPIs without ETL fields emit `signal_type: unavailable` (never fabricated)

## Copy layer (#304)

Rules-only templates from advisory signals. Envelope per `system-design.md` § LLM reasoning:

| Field | Source |
|-------|--------|
| `why` | Linked `AdvisorySignal.one_line` values from `source_kpi_ids` |
| `expected_impact` | `WorkflowRecommendation.expected_impact` |
| `next_steps` | Static template per workflow key |
| `copy_source` | Always `"rules"` |

### Template catalog

| `workflow_key` | Next steps theme |
|----------------|------------------|
| `create_hero_product_1` | Identify growth SKU → prepare listing → track revenue |
| `optimize_product_2` | Review low-conversion listings → update content/pricing → track AOV |
| `create_activity_7a` | Launch campaign for growth SKU → test budget → scale on ROAS |
| `update_activity_7c` | Review live campaigns → rebalance budget/bid → evaluate in 7d |
| `delete_activity_7b` | Pause low-ROAS campaigns → reallocate budget → track CAC/ROAS |
| `replenish_inventory_3` | Reorder at-risk SKUs → adjust ads if stock low → weekly stock check |
| `clear_excess_4` | Identify excess/DSI SKUs → run clearance promo → track turnover |
| `process_order_5` | Fulfill pending orders → verify address/SLA → track accuracy |
| `prevent_cancellation_8a` | Review seller-fault cancel risk → contact/update status → track rate |
| `prevent_return_8b` | Review recent returns → check listing/policy → track return rate |
| `prevent_refund_8c` | Process pending refunds → verify reason/respond → track refund rate |

Authoritative keys: `WORKFLOW_COPY_TEMPLATE_KEYS` in `copy_layer.py` (union of
`NEW_SHOP_WORKFLOW_KEYS` + `MID_LARGE_WORKFLOW_KEYS`).

## Recommendations

Workflow keys align with [`webhook_catalog.py`](../tiktok/webhook_catalog.py) /
[`execution_layer.md`](../../../../docs/product/execution_layer.md) — **not** the
retired P1.8 six-workflow catalog.

## Dependencies

- `juli_backend.services.aggregates` — `build_feature_aggregates` (#300)
- `juli_backend.repositories.repos.ProductsRepo` — SKU ranking proxy (T7)

## Out of scope

- P1.8 `health_check_results` as backend signal authority
- Cloud LLM / Haiku / Ollama copy (Phase 4)
- Celery beat, Redis persistence (persistence lives in `services/action_cards/`, ADR-021)
- Trained T1–T8 inference
