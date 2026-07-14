# backend/src/juli_backend/workers/services/polling

## Purpose

Polls TikTok Shop resources on a schedule, respects rate limits, and hands each
fetched record to the ingest pipeline (ETL). Maintains incremental sync state per
shop. Fujiwa production-read orchestration is the Phase 2 P2-A1 entry point.

## Public API

- `run_fujiwa_poll_cycle(*, session, config, oauth_service, rate_limiter, handoff_fn)` — Fujiwa-only scheduled poll for orders, products, returns, and inventory; refreshes tokens, persists sync state, backs off on rate limits
- `FujiwaPollConfig(app_key, app_secret)` — app credentials for poll cycles
- `sync_orders(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_products(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_returns(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_inventory(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)` — Search Inventory full-snapshot backstop; flattens nested SKUs before `tiktok.inventory.raw` handoff
- `sync_creators(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `backfill_shop(*, creators_resource, rate_limiter, handoff_fn, app_id, shop_id)`

Out-of-scope workers removed (Phase 2 cleanup): `sync_livestreams`,
`sync_settlements`. Incremental inventory changes use webhook `#68 INVENTORY_CHANGED`
(catalog → `tiktok.inventory.raw`); poll remains the reconciliation backstop.

## Dependencies

- `juli_backend.integrations.tiktok` — resource modules, `RateLimiter`, `ProductionReadClientFactory`, exceptions
- `juli_backend.core.security` — `resolve_production_read_credential`, `TikTokOAuthService`
- `juli_backend.repositories.repos` — `TikTokSyncStateRepo`
- `juli_backend.services.ingestion` — `HandoffFn` type

## Key Behaviors

- `run_fujiwa_poll_cycle` resolves Fujiwa `production_read` credentials only; rejects SANDBOX_VN
- Token refresh via `refresh_merchant_tokens` before each cycle
- Sync cursors persisted in `tiktok_sync_state` per shop + endpoint (`orders`, `products`, `returns`, `inventory`)
- Inventory uses `inventory_last_sync_at` watermark only (Search Inventory has no `update_time` filter)
- Rate-limit backoff waits for Redis TTL via `RateLimiter.is_exhausted` / `time_until_reset`; cycle completes without raising
- `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — invoked with
  `(channel, shop_key, payload_bytes)` per record
- Rate limit denied → logs `rate_limited` and returns without handoff
- `TikTokAPIError` → logged, no state update (except creators scope errors)
- `PermissionDeniedError` on creators → re-raised for re-consent flows
- `sync_state` updated **only** when at least one record was handed off
- Channel names: `tiktok.orders.raw`, `tiktok.products.raw`, etc.
- `app_id, shop_id` — rate-limiter bucket and ETL shop key

## Wiring

Use `make_etl_handoff(etl_consumer)` from `juli_backend.services.ingestion`
the same way as the webhook receiver. Schedule `run_fujiwa_poll_cycle` from the
worker beat (Celery) once deployed.
