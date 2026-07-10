# backend/workers/services/polling

## Purpose

Polls TikTok Shop resources on a schedule, respects rate limits, and hands each
fetched record to the ingest pipeline (ETL). Maintains incremental sync state per
shop.

## Public API

- `sync_orders(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_products(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_returns(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_creators(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `backfill_shop(*, creators_resource, rate_limiter, handoff_fn, app_id, shop_id)`

Out-of-scope workers removed (Phase 2 cleanup): `sync_inventory`, `sync_livestreams`,
`sync_settlements`.

## Dependencies

- `backend/integrations/catalog/domain/integrations/tiktok` — resource modules, `RateLimiter`, exceptions
- `backend/integrations/ordering/api/ingestion/handoff` — `HandoffFn` type

## Key Behaviors

- `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — invoked with
  `(channel, shop_key, payload_bytes)` per record
- Rate limit denied → logs `rate_limited` and returns without handoff
- `TikTokAPIError` → logged, no state update (except creators scope errors)
- `PermissionDeniedError` on creators → re-raised for re-consent flows
- `sync_state` updated **only** when at least one record was handed off
- Channel names: `tiktok.orders.raw`, `tiktok.products.raw`, etc.
- `app_id, shop_id` — rate-limiter bucket and ETL shop key

## Wiring

Use `make_etl_handoff(etl_consumer)` from `backend/integrations/ordering/api/ingestion/handoff`
the same way as the webhook receiver.
