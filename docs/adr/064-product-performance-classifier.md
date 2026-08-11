# ADR-064: Product Performance Classifier — real per-product trend classification for Optimize/Create Hero Product

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-011](011-display-grade-analytics-layer.md) (ml_layer.md T1–T10 catalog),
[ADR-063](063-t10-inventory-reorder-engine.md) (lazy-compute-at-Inputs-step pattern).
**Does not change:** `services/scoring` daily signal computation or card *presence* triggering
(`compute_revenue_by_sku` / `compute_conversion_rate_by_category` remain the reason
`create_hero_product_1` / `optimize_product_2` appear in the Decisions list at all);
`WorkflowRecommendation` / `ScoringSignals` schemas; `run_create_hero_product_chain` /
`run_optimize_product_chain` execution logic.

## Context

Today, `_compute_revenue_by_sku` (`services/scoring/signals.py`) selects a product with a
single static pick: `max(products, key=lambda p: float(p.revenue or 0))` — no trend, no
conversion awareness, no bad-case handling. The same signal feeds both
`create_hero_product_1` and `optimize_product_2` with no differentiation between "this
product is winning, clone it" and "this product needs fixing."

Two candidate algorithms were evaluated against the actual write surface of both
workflows and rejected:
- `ai/forecasting.get_velocity_changes` — direction-only (accelerating/decelerating) on a
  synthetic per-SKU proxy (shop order count split evenly across active SKUs); no price,
  margin, or conversion signal, so it cannot drive either workflow's real decision.
- `ai/recommendations.get_product_push_suggestions` — its own `cta` text
  ("Đẩy sản phẩm X lên livestream tối nay") reveals it's a livestream-merchandising
  ranker, not a listing/pricing tool; zero connection to
  `WORKFLOW_TOOL_CATALOG`; its "margin" component is a mislabeled avg-revenue-per-unit
  (no COGS field exists anywhere in the schema).

Real, unused, per-product data exists: `AnalyticsPerformanceInterval` (`grain="product"`
rows carry `tiktok_product_id`, `gmv`, `conversion_rate`, `ctr`, real Partner-API-synced
time series) — today only ever collapsed into a shop-wide mean
(`compute_analytics_weighted_product_ctr`), never read per-product. `OrderItem`
(`tiktok_product_id`, `line_total`, joined to `order.created_at`) gives a real fallback
GMV signal when Analytics rows aren't synced yet for a product — same honest-unavailable
posture used throughout `signals.py`.

## Decision

**Replace the static top-revenue pick with a rules-based Product Performance Classifier**,
computed lazily at Inputs-review time (same pattern as T10 in ADR-063), using 30d-vs-prior-30d
windows (matching the existing `ROLLING_WINDOW_DAYS = 30` convention) on real per-product
`gmv` and `conversion_rate` from `AnalyticsPerformanceInterval` (falling back to
`OrderItem.line_total` sums when Analytics rows are absent for a product).

| GMV trend (±15%) | Conversion trend (±15%) | Classification | Routes to | Copy posture |
|---|---|---|---|---|
| Up | Up or flat | **Scale** | Create Hero Product | Clone-the-winner framing |
| Down | Down | **Fix — demand & efficiency** | Optimize Product | Decline framing; T9 price cut eligible |
| Up | Down | **Fix — inefficient traffic** | Optimize Product | "Converting worse despite volume" framing; T9 price cut eligible |
| Flat / insufficient history | — | **Explore** | Optimize Product | Distinct, lower-confidence framing; **no forced `price_update`** |

**Never return nothing.** If the top-ranked product doesn't clear the ±15% threshold in
either direction, or there isn't enough history to classify any product, the classifier
still selects the most-recently-active eligible product and returns **Explore** rather than
suppressing the card — Explore always routes to Optimize Product (which still runs
TikTok's own "Get Suggestions" listing refresh via `run_optimize_product_chain` even
without a Juli price move), just with copy that doesn't overclaim a detected problem.

Fix classifications are eligible for the T9 fee-adjusted price rule (ADR-066) as the
`price_update` input; Explore classifications never pass a `price_update` — the workflow
still runs, it just doesn't force a pricing claim the data doesn't support.

## Consequences

- Card *presence* in the Decisions list is unchanged — still driven by the existing real
  `revenue_by_sku` / `conversion_rate_by_category` KPI signals. This ADR only upgrades
  *which specific product* gets selected and *why*, at the point the seller opens the card.
- Product selection quality moves from a static single-field pick to a real trend- and
  conversion-aware classification, without adding fields to `WorkflowRecommendation` /
  `ScoringSignals` — consistent with the minimal-blast-radius approach set by T10.
- Sellers always see an actionable Optimize/Create Hero Product card rather than a dead
  end — Explore is a deliberate weak-signal fallback, not silence.
- `docs/ml/ml_layer.md`'s locked T1–T10 catalog does not yet register this technique; it
  is workflow-scoped like T9/T10 but is a new addition, not a promotion of an existing
  T-slot. Follow-up: add it to `ml_layer.md`'s technique catalog under Architect review —
  out of scope for this ADR.

## Options considered

| Option | Outcome |
|--------|---------|
| Reuse `get_velocity_changes` as-is | Rejected — no price/margin/conversion features, cannot drive either workflow's actual decision |
| Reuse `get_product_push_suggestions` as-is | Rejected — built for livestream push, not listing/pricing; mislabeled margin proxy |
| Suppress the card entirely on weak/flat signal ("Hold") | Rejected per user direction — never suggest nothing; replaced with Explore → Optimize Product, differently worded |
| Bake classification into the daily `ScoringSignals` batch (per-product field) | Rejected — reshapes shared dataclasses for one workflow's benefit, same reasoning as ADR-063 |
| **Lazy per-product classifier at Inputs-review, real `AnalyticsPerformanceInterval`/`OrderItem` data, Explore fallback (chosen)** | Real algorithm on real data, minimal blast radius, always actionable |
