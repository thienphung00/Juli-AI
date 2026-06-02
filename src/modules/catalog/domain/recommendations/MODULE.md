# Module: recommendations

## Responsibility
Operational recommendations for sellers: which products to push on livestream,
how to optimize stream performance, and which host-product pairing should be
used next. Output is always plain Vietnamese with actionable CTAs. Supports
LLM-assisted copy generation with quota-aware fallback to deterministic rules.

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
  — recommends creator-product pairings using creator historical stream
  performance + product push score.
- `HostProductMatch` — `creator_id`, `creator_name`, `tiktok_product_id`,
  `product_name`, `match_score`, `message`, `cta`, `source`

## Dependencies
- `src.data.models` — `Product`, `InventoryItem` (read-only)
- `src.intelligence.forecasting` — `get_velocity_changes`, `get_low_stock_risks`
- `src.intelligence.scoring` — `score_livestream`
- `src.data.models.Recommendation` — read-only daily quota counter for LLM usage

## Invariants
- Read-only against `data`; persistence via `RecommendationsRepo` is reserved for API slice (#43)
- LLM calls are optional and must respect a per-shop daily cap
- When LLM is unavailable or budget is exhausted, deterministic rule templates are used
- User-facing strings in plain Vietnamese without analytics jargon

## Owners
- domain: recommendations
- code: src/recommendations/
