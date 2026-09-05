# backend/src/juli_backend/repositories

## Purpose

Data access, one module per aggregate, all on the contract stated in `_base.py`:
a repository borrows the caller's `AsyncSession` and never commits; anything
under a shop extends `ShopScopedRepo` so `shop_id` filtering is structural;
`get` raises `NotFound` while `find`/`get_by_*` return `None`; timestamps are
naive UTC (`utc_now_naive`, #1138); `upsert` is declared via `_lookup_attrs`
and inherited, refusing stale `update_time` and surviving a concurrent insert.

## Public API

Import from the package root: `from juli_backend.repositories import OrdersRepo`.
`repos.py` re-exports the same names for callers written before the split.

| Module | Owns |
|--------|------|
| `identity` | `UsersRepo`, `ShopsRepo` |
| `tiktok_credentials` | `TikTokCredentialRepo` (tokens encrypted at rest), `TikTokSyncStateRepo` |
| `commerce` | `OrdersRepo`, `OrderItemsRepo`, `ReturnsRepo`, `ProductsRepo`, `InventoryRepo`, `SettlementsRepo` |
| `analytics` | `CreatorsRepo`, `LivestreamsRepo`, `AnalyticsPerformanceRepo`, `GoldKpiEnvelopesRepo`, `AnalyticsKpiEnvelopesRepo` |
| `decisions` | `AlertConfigsRepo`, `AlertHistoryRepo`, `RecommendationsRepo`, `ActionCardsRepo` |
| `graph` | `GraphRepo` |
| `bronze` | `BronzeRawPayloadsRepo` base + the four bronze table writers |
| `workflow` | `WorkflowWebhookSignalsRepo`, `WebhookRawEventsRepo`, `ToolExecutionsRepo`, `WorkflowOutcomeRecordsRepo` |
| `backfill` | `AnalyticsBackfillPartitionsRepo`, `redact_secrets` |
| `production_write` | `ProductionWriteAuthorizationsRepo` |

## Adding a repository

Read `_base.py`. Set `_model` and, for synced entities, `_lookup_attrs`. Build
every query through `self._scoped(shop_id, ...)`. Put it in the module that owns
its aggregate, or add a module if it is a new aggregate, and export it from
`__init__.py`. Test it the way `tests/unit/test_repositories_commerce.py` does.

## Must not

- `commit()` or `rollback()` — the transaction belongs to the caller.
- Hand-write `Model.shop_id == shop_id` inside a `ShopScopedRepo` subclass.
- Import from `services`, `api`, `workers` or `integrations`
  (`.importlinter.toml`: `repositories -> {models, database}`). The one
  grandfathered edge is `tiktok_credentials -> integrations.tiktok`, carried in
  the baseline and documented in that module.
- Write aware datetimes into `TIMESTAMP WITHOUT TIME ZONE` columns.
- Bypass the one-writer map for medallion tables (`database/MODULE.md`).
