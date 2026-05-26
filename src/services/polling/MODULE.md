# Module: services/polling

## Responsibility
Polls TikTok Shop resources on a schedule, respects rate limits, and publishes
each fetched record to a Kafka topic. Maintains incremental sync state per
resource via `update_time` cursors.

## Public Interface

All workers are async functions with the same calling convention:

- `sync_orders(*, resource, rate_limiter, publish_fn, app_id, shop_id,
  sync_state) -> None`
- `sync_products(*, resource, rate_limiter, publish_fn, app_id, shop_id,
  sync_state) -> None`
- `sync_inventory(*, resource, rate_limiter, publish_fn, app_id, shop_id,
  sync_state) -> None`
- `sync_creators(*, resource, rate_limiter, publish_fn, app_id, shop_id,
  sync_state) -> None` — Affiliate API; re-raises `PermissionDeniedError`
- `sync_livestreams(*, resource, rate_limiter, publish_fn, app_id, shop_id,
  sync_state) -> None` — post-stream summaries; re-raises `PermissionDeniedError`
- `sync_settlements(*, resource, rate_limiter, publish_fn, app_id, shop_id,
  sync_state) -> None` — Finance API; values pending 7-14 days
- `backfill_shop(*, creators_resource, livestreams_resource,
  settlements_resource, rate_limiter, publish_fn, app_id, shop_id)
  -> dict[str, Any]` — 90-day initial backfill; caller must stagger per shop
- `BACKFILL_WINDOW_SECONDS` — constant: 90 days in seconds

Common parameters:

- `resource` — an instance of `OrdersResource` / `ProductsResource` /
  `InventoryResource` / `CreatorsResource` / `LivestreamsResource` /
  `SettlementsResource`
- `rate_limiter: RateLimiter` — Redis-backed limiter (from
  `integrations/tiktok`)
- `publish_fn: Callable[[str, str, bytes], Awaitable[None]]` — invoked with
  `(topic, partition_key, payload_bytes)` per record
- `app_id, shop_id` — identifiers for rate-limiter bucket and Kafka
  partitioning
- `sync_state: dict` — mutated in place; stores `{resource}_last_update_time`
  cursors

## Dependencies
- `src.integrations.tiktok.rate_limiter` — `RateLimiter`
- `src.integrations.tiktok.exceptions` — `TikTokAPIError`, `PermissionDeniedError`
- Standard library: `json`, `logging`, `time`

The resource objects are injected by the caller — the worker module does not
construct `TikTokClient` itself.

## Invariants
- Each worker checks the rate limiter before any external call; on exhaustion,
  it logs `rate_limited` and returns without publishing
- `TikTokAPIError` is caught, logged with `exc_info`, and swallowed — the
  caller decides whether to retry on the next schedule tick
- **Exception:** `sync_creators` and `sync_livestreams` re-raise
  `PermissionDeniedError` (scope_missing) so the caller can trigger re-consent
- `sync_state` is updated **only** when at least one record was published
  successfully (no off-by-one on empty fetches)
- Workers are idempotent at the transport level — re-running with the same
  `sync_state` re-publishes the same window (deduplication is downstream)
- Kafka topic names are constants per worker (`tiktok.orders.raw`,
  `tiktok.products.raw`, `tiktok.inventory.raw`, `tiktok.creators.raw`,
  `tiktok.livestreams.raw`, `tiktok.settlements.raw`) — not derived from input
- Partition key is always `shop_id` — preserves per-shop ordering downstream
- `backfill_shop` sets a 90-day lookback window and calls all three new sync
  functions sequentially; the caller must stagger across shops

## Owners
- domain: integrations
- code: `src/services/polling/`
- tests: `tests/unit/test_polling.py`, `tests/integration/test_polling_*.py`
