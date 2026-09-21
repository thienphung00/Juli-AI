# backend/src/juli_backend/workers/services/polling

## Purpose

Polls TikTok Shop resources on a schedule, respects rate limits, and hands each
fetched record to the ingest pipeline (ETL). Maintains incremental sync state per
shop. Fujiwa production-read orchestration is the Phase 2 P2-A1 entry point.

## Public API

- `run_fujiwa_poll_cycle(*, session, config, oauth_service, rate_limiter, handoff_fn, shop_id=None, resolve_credential=None, factory=None, create_resources=None, sync_state_repo=None, sleep=asyncio.sleep)` — scheduled/manual poll for orders, products, returns, inventory, and analytics; refreshes tokens, persists sync state, backs off on rate limits (also the ADR-021 manual-refresh poll hook). the shop_id keyword names the shop being polled (#1995): given, the credential is resolved by core.security's per-shop read resolver and must be a read capability **owned by that shop**, so a connecting seller polls under their own token; omitted, the fleet-wide Celery beat behaviour is unchanged (resolve the configured production-read merchant)
- `run_fujiwa_material_resource_fetch(...)` — same parameters and the same shop_id semantics; the material-precompute entry point
- `ResolveCredentialFn` — `Callable[[AsyncSession, uuid.UUID | None], Awaitable[TikTokCredential]]`; the credential-resolution seam both entrypoints inject. Widened by #1995 to carry the shop, because the poll is per-shop and the one-parameter alias could not express `resolve_read_credential_for_shop`
- `FujiwaPollConfig(app_key, app_secret)` — app credentials for poll cycles
- `SyncOutcome(resource, shop_id, fetched, persisted, failed, pages, backfill, skipped, error)` — what one step actually did (#1950's triple). `ok` is false when the fetch errored, any row was rejected, or the step dropped everything; `dropped_everything` is `fetched > 0 and persisted == 0`. `persisted` counts rows the ETL handoff accepted without raising, which is NOT proof of a committed row: `HandoffFn` is typed `-> None` and `make_etl_handoff` discards `EtlConsumer.ingest`'s verdict, so a DLQ'd row counts as accepted
- `PollStepDroppedRowsError(outcome)` — raised by a step that fetched rows from the vendor and persisted none of them. Carries the `SyncOutcome`
- `PollCycleTimeoutError(*, stage, budget_seconds, elapsed_seconds)` — raised when a cycle outruns its wall-clock budget, naming the stage it stopped at
- `PollCycleFailedError(failures, *, shop_id)` — raised at the END of a cycle in which any step landed nothing it should have landed (#1950 criterion 2): a failed vendor fetch, or rows fetched and all rejected. Narrower than `ok=False` on purpose — a PARTIAL persist does not fail the cycle, because one malformed row in 3,581 must not fail a seller's manual refresh; it is recorded instead, as tiktok_sync_state.last_outcome='failed' with real counts and no advance of .last_success_at, and as `degraded_steps` on the `poll_cycle_outcome` record. This is what turns the three fetch-error arms that `report` and return (`sync_orders`/`sync_products`/`sync_returns`) into a failed poll instead of a silent one; it is raised AFTER `sync_state` and the outcome records are written, so the evidence survives the failure. Carries the failing `SyncOutcome`s
- `cycle_budget_seconds()` — the cycle's wall-clock budget, from `CYCLE_BUDGET_SECONDS_ENV` (`TIKTOK_POLL_CYCLE_BUDGET_SECONDS`, default 1800s). Bounds *scheduling*, not execution: it refuses a stage that has not begun and cancels one parked on an `await`, but cannot preempt a synchronous `requests` or redis-py call in flight. The stage's remaining budget is published as the enclosing `pagination_scope`, so a per-fetch budget composes with it by `min` rather than by addition; the residual overrun is one in-flight vendor request (the 15s socket timeout) plus the current page's handoff loop
- `CYCLE_BUDGET_SECONDS_ENV` — name of that environment variable
- `sync_orders(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)` — returns a `SyncOutcome`
- `sync_products(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)` — returns a `SyncOutcome`
- `sync_returns(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)` — returns a `SyncOutcome`
- `sync_inventory(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state, list_product_ids, page_size=DEFAULT_INVENTORY_PAGE_SIZE)` — returns a `SyncOutcome`; Search Inventory full-snapshot backstop; flattens nested SKUs before `tiktok.inventory.raw` handoff. `list_product_ids` is required, not defaulted: the endpoint hard-requires `product_ids` (#1948), and a default would reintroduce the silent empty fetch. Raises `TikTokAPIError` and `ValueError` rather than swallowing them — an empty `list_product_ids` result is a clean zero, not a failure. `pages` is always 0 by construction: Search Inventory is a single POST per batch and never walks a cursor, so nothing increments the scope's page counter (#1969 review F6)
- `sync_analytics(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state, promotion_resource=None, now=None)` — returns a `SyncOutcome` whose `fetched` counts rows offered (the step fans out over ~10 endpoints, so no single vendor row count exists); Analytics GET wire set (A-31–A-39) + optional A-25; date-window + pagination; hands normalized rows to ETL (#425). Each endpoint's `*_last_sync_at` watermark is STAGED where the write used to be and committed only if that endpoint's own rows landed (#1950 criterion 3) — an endpoint that offered rows and persisted none is held back and logs `poll_watermark_held_back`; an endpoint that offered nothing still advances, because a genuine empty window is not a failure
- `sync_creators(*, resource, rate_limiter, handoff_fn, app_id, shop_id, sync_state)` — returns `None`
- `backfill_shop(*, creators_resource, rate_limiter, handoff_fn, app_id, shop_id)`
- `ProductIdsFn` — `Callable[[], Awaitable[list[str]]]`; the shop's already-synced TikTok product ids that `sync_inventory` batches through, `page_size` at a time
- `DEFAULT_INVENTORY_PAGE_SIZE` — product ids per Search Inventory request (30; the only batch size confirmed against the live endpoint)

Out-of-scope workers removed (Phase 2 cleanup): `sync_livestreams`,
`sync_settlements`. Incremental inventory changes use webhook `#68 INVENTORY_CHANGED`
(catalog → `tiktok.inventory.raw`); poll remains the reconciliation backstop.

## Dependencies

- `juli_backend.integrations.tiktok` — resource modules, `RateLimiter`, `ProductionReadClientFactory`, exceptions
- `juli_backend.core.security` — `resolve_production_read_credential` (fleet-wide entry only), `TikTokOAuthService`, and since #1995 the per-shop read resolver #1365 added beside them
- `juli_backend.repositories.repos` — `TikTokSyncStateRepo`
- `juli_backend.services.ingestion` — `HandoffFn` type

## Key Behaviors

- `run_fujiwa_poll_cycle` accepts any **read-capable** credential (production_read or seller_connect) and, when a shop_id is given, only one owned by that shop; it rejects SANDBOX_VN by capability *and* by merchant id. The guard runs before the sticky shop scope is entered, so an unverified credential never confers a tenant scope (#1995)
- The vendor client signs with the credential's own merchant authorization id, not the deployment-configured production merchant constant — the change that lets two shops call the vendor under their own authorizations
- Token refresh via `refresh_merchant_tokens` before each cycle
- Sync cursors persisted in `tiktok_sync_state` per shop + endpoint (`orders`, `products`, `returns`, `inventory`, analytics keys)
- Inventory uses `inventory_last_sync_at` watermark only (Search Inventory has no `update_time` filter)
- Analytics uses `start_date_ge` / `end_date_lt` (YYYY-MM-DD) one-day UTC windows; LIVE A-26–A-29 not wired
- Rate-limit backoff waits for Redis TTL via `RateLimiter.is_exhausted` / `time_until_reset`.
  A cycle can now fail in three ways, all loud: MID-CYCLE on an inventory vendor error or a
  non-dict inventory response (#1948, aborts before `sync_analytics`); mid-cycle on a
  `PollStepDroppedRowsError`; and AT THE END on `PollCycleFailedError` when any step reported
  `ok=False` (#1950). The last one is what closes the swallow #1969 left in place: a fetch error
  in orders/products/returns is reported by the step and returned, and before #1950 the cycle
  completed over it. Every path persists what completed — `orchestrate.py::_record_cycle` writes
  partial `sync_state` AND the per-endpoint verdicts before the exception propagates, so a
  step-4 failure discards neither steps 1–3's watermarks nor the record of what broke. Analytics
  not running at all on an inventory failure remains a known, accepted cost
- `handoff_fn: Callable[[str, str, bytes], Awaitable[None]]` — invoked with
  `(channel, shop_key, payload_bytes)` per record
- Rate limit denied → logs `rate_limited` and returns without handoff
- `TikTokAPIError` → logged with the step's outcome at ERROR, no state update, and the step's
  `ok=False` verdict fails the cycle at the end (#1950). `sync_inventory` re-raises on the spot
  instead (#1948), and creators scope errors re-raise for re-consent
- `PermissionDeniedError` on creators → re-raised for re-consent flows
- `sync_state` updated **only** when at least one record was handed off — for the four search steps inline (`if rows and outcome.persisted`), for the ~10 analytics endpoints through `_StepRun.stage_watermark` / `flush_watermarks`, which charges each endpoint the rows offered between its stage point and the next one. The flush also runs from `_StepRun.__exit__`, so a step that dies at endpoint 4 of 10 keeps the three that worked
- `tiktok_sync_state` also records the LAST VERDICT per endpoint (#1950 criterion 4), in six columns owned by `backend/models`: tiktok_sync_state.last_outcome (one of ok, skipped, dropped, failed), .last_outcome_at, .last_fetched, .last_persisted, .last_error and .last_success_at. Written by `TikTokSyncStateRepo.record_outcomes`, which INSERTS a row for an endpoint that has no cursor — so `last_success_at IS NULL` answers "has this endpoint ever succeeded" instead of it being inferred from a missing row. This is the only half of the outcome that survives the Celery worker, where `logger.extra` fields are dropped (#1978)
- Channel names: `tiktok.orders.raw`, `tiktok.products.raw`, etc.
- `app_id, shop_id` — rate-limiter bucket and ETL shop key

## Wiring

Use `make_etl_handoff(etl_consumer)` from `juli_backend.services.ingestion`
the same way as the webhook receiver. Schedule `run_fujiwa_poll_cycle` from the
worker beat (Celery) once deployed.
