# Module: recommendations

## Responsibility
Rule-based operational recommendations for sellers: which products to push on
livestream and (future slices) restock timing. Plain Vietnamese copy with
actionable CTAs. No LLM dependency in MVP — heuristics over `data` and
`intelligence/forecasting`.

## Public Interface

### Product push
- `get_product_push_suggestions(session, shop_id, *, limit=10) -> list[ProductPushSuggestion]`
  — ranks active products by composite trend + margin + stock score.
- `ProductPushSuggestion` — `tiktok_product_id`, `product_name`, `sku_id`,
  `composite_score`, `message`, `cta`

## Dependencies
- `src.data.models` — `Product`, `InventoryItem` (read-only)
- `src.intelligence.forecasting` — `get_velocity_changes`, `get_low_stock_risks`

## Invariants
- Read-only against `data`; persistence via `RecommendationsRepo` is reserved for API slice (#43)
- No OpenAI / LiteLLM / external model calls
- User-facing strings in plain Vietnamese without analytics jargon

## Owners
- domain: recommendations
- code: src/recommendations/
