# Module: recommendations

> **Phase-1 matching seed.** `get_host_product_matching` already produces
> creator↔product matches with a score + justification + CTA — the smallest delta
> toward the Creator ↔ Shop Matching product. This module is the basis for the
> future `matching/` + `agents/` layers (see `docs/decisions/006-matching-pivot.md`).
> The `intelligence/{scoring,forecasting}` dependencies below are **legacy signals**
> to be folded into `matching/prediction` or removed.

## Responsibility
Decision-focused recommendations: which creator-product pairing to use next, plus
(legacy) product-push and stream-optimization suggestions. Output is always plain
Vietnamese with actionable CTAs. Supports LLM-assisted copy generation with
quota-aware fallback to deterministic rules.

## Public Interface

### Product push
- `get_product_push_suggestions(session, shop_id, *, limit=10) -> list[ProductPushSuggestion]`
  — ranks active products by composite trend + margin + stock score.
- `ProductPushSuggestion` — `tiktok_product_id`, `product_name`, `sku_id`,
  `composite_score`, `message`, `cta`

### Stream optimization
- `get_stream_optimization(session, shop_id, session_id, *, max_calls_per_day=20, llm_generator=None) -> StreamOptimizationSuggestion`
  — returns a Vietnamese optimization suggestion for one livestream using
  `intelligence/scoring` and optional LLM text generation.
- `StreamOptimizationSuggestion` — `session_id`, `score_grade`, `message`, `cta`,
  `source` (`"llm"` or `"rules"`)

### Host-product matching
- `get_host_product_matching(session, shop_id, *, limit=3, max_calls_per_day=20, llm_generator=None) -> list[HostProductMatch]`
  — ranks creator↔product pairings by commerce-graph edges (`potential_match`,
  `has_sold`) plus stream performance and product-push score; emits predicted
  outcomes and action CTAs.
- `HostProductMatch` — `creator_id`, `creator_name`, `tiktok_product_id`,
  `product_name`, `match_score`, `message`, `cta`, `source`, `predicted_outcome`,
  `action_type`, `confidence`, `computed_at`
- `prediction.py` — `PredictedOutcome`, `estimate_predicted_outcome`,
  `confidence_from_score`, `select_action_type`, `build_action_cta`,
  `build_decision_message`

## Dependencies
- `src.shared.utils.data.repos.GraphRepo` — commerce graph edges for ranking
- `src.shared.utils.data.models` — `Creator`, `Product`, `Livestream`, `InventoryItem` (read-only)
- `src.modules.catalog.domain.intelligence.forecasting` — `get_velocity_changes`, `get_low_stock_risks` (legacy signal)
- `src.modules.catalog.domain.intelligence.scoring` — `score_livestream` (legacy signal)
- `src.shared.utils.data.models.Recommendation` — read-only daily quota counter for LLM usage

## Invariants
- Read-only against `data`; persistence via `RecommendationsRepo` is reserved for API slice (#43)
- LLM calls are optional and must respect a per-shop daily cap
- When LLM is unavailable or budget is exhausted, deterministic rule templates are used
- User-facing strings in plain Vietnamese without analytics jargon

## Owners
- domain: recommendations
- code: src/modules/catalog/domain/recommendations/
