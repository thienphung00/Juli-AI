# backend/src/juli_backend/workers/services/polling

## Purpose

Polls TikTok Shop resources on a schedule, respects rate limits, and hands each
fetched record to the ingest pipeline (ETL). Maintains incremental sync state per
shop. Fujiwa production-read orchestration is the Phase 2 P2-A1 entry point.

## Public API

- `run_fujiwa_poll_cycle(*, session, config, oauth_service, rate_limiter, handoff_fn)` — Fujiwa-only scheduled poll for orders, products, returns, inventory, and analytics; refreshes tokens, persists sync state, backs off on rate limits (also the ADR-021 manual-refresh poll hook)
- `FujiwaPollConfig(app_key, app_secret)` — app credentials for poll cycles
- `sync_orders(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_products(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_returns(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `sync_inventory(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state, list_product_ids, page_size=DEFAULT_INVENTORY_PAGE_SIZE)` — Search Inventory full-snapshot backstop; flattens nested SKUs before `tiktok.inventory.raw` handoff. The endpoint requires `product_ids` (#1948), so `list_product_ids` is required, not defaulted — the caller owns the product-id source. Raises `TikTokAPIError` and `ValueError` rather than swallowing them
- `sync_analytics(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state, promotion_resource=None)` — Analytics GET wire set (A-31–A-39) + optional A-25; date-window + pagination; hands normalized rows to ETL (#425) and updates sync_state watermarks
- `sync_creators(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)`
- `backfill_shop(*, creators_resource, rate_limiter, handoff_fn, app_id, shop_id)`
- `ProductIdsFn` — `Callable[[], Awaitable[list[str]]]`; the shop's already-synced TikTok product ids that `sync_inventory` pages through
- `DEFAULT_INVENTORY_PAGE_SIZE` — product ids per Search Inventory request (30; the only batch size confirmed against the live endpoint)

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
- Sync cursors persisted in `tiktok_sync_state` per shop + endpoint (`orders`, `products`, `returns`, `inventory`, analytics keys)
- Inventory uses `inventory_last_sync_at` watermark only (Search Inventory has no `update_time` filter)
- Analytics uses `start_date_ge` / `end_date_lt` (YYYY-MM-DD) one-day UTC windows; LIVE A-26–A-29 not wired
- Rate-limit backoff waits for Redis TTL via `RateLimiter.is_exhausted` / `time_until_reset`; the
  cycle completes without raising *except* on an inventory vendor error or a non-dict inventory
  response, which abort the cycle before `sync_analytics` and before the sync-state save (#1948)
- `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — invoked with
  `(channel, shop_key, payload_bytes)` per record
- Rate limit denied → logs `rate_limited` and returns without handoff
- `TikTokAPIError` → logged, no state update (except creators scope errors, and `sync_inventory`,
  which re-raises: a sync that drops every row must not look like one with nothing to sync, #1948)
- `PermissionDeniedError` on creators → re-raised for re-consent flows
- `sync_state` updated **only** when at least one record was handed off
- Channel names: `tiktok.orders.raw`, `tiktok.products.raw`, etc.
- `app_id, shop_id` — rate-limiter bucket and ETL shop key

## Wiring

Use `make_etl_handoff(etl_consumer)` from `juli_backend.services.ingestion`
the same way as the webhook receiver. Schedule `run_fujiwa_poll_cycle` from the
worker beat (Celery) once deployed.
