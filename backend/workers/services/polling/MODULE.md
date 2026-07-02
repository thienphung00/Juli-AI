# src/services/polling

## Purpose

Polls TikTok Shop resources on a schedule, respects rate limits, and hands each
fetched record to the ingest pipeline (ETL). Maintains incremental sync state per
shop.

## Public API

- `sync_orders(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_products(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_inventory(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_creators(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_livestreams(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_settlements(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `backfill_shop(*, creators_resource, livestreams_resource, settlements_resource,
  rate_limiter, handoff_fn, app_id, shop_id)`

`publish_fn` is a deprecated alias for `handoff_fn` on all workers.

## Dependencies

- `src/integrations/tiktok` — resource modules, `RateLimiter`, exceptions
- `src/ingestion/handoff` — `HandoffFn` type

## Key Behaviors

- `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — invoked with
  `(channel, shop_key, payload_bytes)` per record
- Rate limit denied → logs `rate_limited` and returns without handoff
- `TikTokAPIError` → logged, no state update (except creators/livestreams scope errors)
- `PermissionDeniedError` on creators/livestreams → re-raised for re-consent flows
- `sync_state` updated **only** when at least one record was handed off
- Channel names: `tiktok.orders.raw`, `tiktok.products.raw`, etc. (see `src/etl/channels.py`)
- `app_id, shop_id` — rate-limiter bucket and ETL shop key

## Wiring

Use `make_etl_handoff(etl_consumer)` from `src/ingestion/handoff` the same way as
the webhook receiver.
