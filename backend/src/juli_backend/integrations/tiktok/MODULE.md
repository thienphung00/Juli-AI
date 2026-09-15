# Module: integrations/tiktok

## Responsibility
Provides a typed, signed, rate-limited HTTP client for the TikTok Shop Partner
API plus OAuth lifecycle management.

## Public Interface

Import from the package root only:

```python
from juli_backend.integrations.tiktok import TikTokAuth, TikTokClient, ...
```

Deep imports of leaf modules (``resources/*``, ``guarded_client``, ``guards``,
``capabilities``, etc.) are internal and forbidden for external callers.

### Package facade (`__init__.py`)

Matches ``__all__`` — re-exports only:

- **Authentication** — ``TikTokAuth``, ``TikTokBusinessAdvertiserAuth``,
  ``TikTokBusinessAccountHolderAuth``, ``DEFAULT_OPEN_API_BASE_URL``
- **HTTP client** — ``TikTokClient``
- **Pagination budgeting** (#1969) — ``pagination_scope``,
  ``current_pagination_scope``, ``PaginationScope``, ``TikTokPaginationError``,
  ``TikTokPaginationTruncatedError``, ``TikTokPaginationTimeoutError``
  — a cold-start backfill and a routine incremental poll hit the same endpoints
  and need different page budgets and different verdicts (truncating a first
  read is a failure; truncating a delta is not). The caller that knows which job
  it is doing lives above the resource wrappers, so the mode travels in a
  context variable rather than on the client or the endpoint
- **Safe identifier rendering** — ``redact_shop_identifier`` (never log a full
  ``shop_cipher``; re-exported for ``services/tiktok/credential_binding.py``,
  which may only reach this package root under the depth-2 import cap)
- **Request signing** — ``sign_request``
- **Rate limiting** — ``RateLimiter``
- **API path constants** — ``ANALYTICS_BESTSELLING_PRODUCTS_PATH``,
  ``ANALYTICS_BESTSELLING_VIDEOS_PATH``, ``ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH``,
  ``ANALYTICS_LIVE_PERFORMANCE_LIST_PATH``, ``ANALYTICS_SHOP_PERFORMANCE_PATH``,
  ``ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH``, ``ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH``,
  ``CANCELLATION_SEARCH_PATH``,
  ``FINANCE_STATEMENTS_PATH``, ``INVENTORY_SEARCH_PATH``,
  ``MARKETPLACE_CREATORS_SEARCH_PATH``, ``ORDER_SEARCH_PATH``, ``PRODUCT_SEARCH_PATH``,
  ``RETURN_SEARCH_PATH``,
  ``analytics_shop_performance_per_hour_path``, ``analytics_shop_product_performance_path``,
  ``analytics_shop_sku_performance_path``, ``promotion_activity_path``
- **Client factories** — ``ClientFactoryConfig``, ``ProductionReadClientFactory``,
  ``ProductionReadResources``, ``SandboxWriteClientFactory``, ``SandboxWriteResources``
- **Merchant isolation** — ``PRODUCTION_AUTH_ID``, ``SANDBOX_AUTH_ID``,
  ``TikTokCapability``, ``resolve_merchant_context``, ``is_cross_merchant_lookup``
- **Vendor → ingest mapping** — ``analytics_snapshot_key``,
  ``expand_analytics_live_session``, ``expand_analytics_product_detail``,
  ``expand_analytics_product_list_item``, ``expand_analytics_shop_performance``,
  ``expand_analytics_shop_performance_per_hour``, ``expand_analytics_sku_detail``,
  ``expand_analytics_sku_list_item``, ``expand_inventory_search``,
  ``expand_order_line_items``, ``normalize_cancellation``, ``normalize_creator``,
  ``normalize_inventory``, ``normalize_livestream``, ``normalize_order``,
  ``normalize_product``, ``normalize_return``, ``normalize_statement``
- **Resources** — ``strip_nones``, ``AnalyticsResource``, ``AuthorizationResource``,
  ``CreatorsResource``, ``FulfillmentResource``, ``InventoryResource``,
  ``LivestreamsResource``, ``OrdersResource``, ``ProductsResource``,
  ``PromotionResource``, ``ReturnsResource``, ``SettlementsResource``
- **Exceptions** — ``TikTokAPIError``, ``AuthenticationError``,
  ``PermissionDeniedError``, ``ResourceNotFoundError``, ``RateLimitError``,
  ``TikTokSystemError``, ``TransportGuardError``, ``error_from_response``
- **Selective (OAuth verify slice)** — ``TikTokSchemaError``

### Pagination budget knobs (`client.py`, #1969)

Read by the shared paginator, not re-exported through ``__all__`` — they are operational
dials, so they are documented here rather than widened into the facade. Each
reader resolves its environment variable on every call, so a deploy can change
a budget without a code change.

- ``max_pages`` / ``MAX_PAGES_ENV`` — page cap for a routine INCREMENTAL fetch
  (``TIKTOK_MAX_PAGES``, default 20). Exhausting it logs
  ``tiktok_pagination_max_pages_reached`` and returns what landed; the next
  cycle resumes from the same watermark
- ``backfill_max_pages`` / ``BACKFILL_MAX_PAGES_ENV`` — page budget for a
  COLD-START backfill (``TIKTOK_BACKFILL_MAX_PAGES``, default 400; 20,000 rows
  at page_size 50). Exhausting it RAISES, because there is no next cycle that
  repairs a half-read history
- ``default_fetch_budget_seconds`` / ``FETCH_BUDGET_SECONDS_ENV`` — wall-clock
  budget for one paginated fetch when the caller names none
  (``TIKTOK_FETCH_BUDGET_SECONDS``, default 600s). Checked BETWEEN pages, which
  is the only place this layer can check anything: ``requests`` is synchronous,
  so a page already in flight is bounded only by the per-request socket timeout

## Dependencies
- `requests` — HTTP transport (sync)
- `redis` (rate_limiter only) — token-bucket persistence
- Standard library: `hashlib`, `hmac`, `json`, `logging`, `time`, `urllib.parse`

No imports from other internal modules — this module is a leaf in the
dependency graph.

## Invariants
- Every signed request includes `app_key`, `timestamp`, `access_token` query
  parameters, with `sign` computed last over the canonical (sorted, filtered)
  parameter string + body
- `sign` and `access_token` are excluded from the signature canonical string
- `_handle_response` raises a typed exception when the TikTok response has a
  non-zero `code`; success responses return the `data` payload
- `RateLimiter.acquire` is atomic (uses `INCR` + conditional `EXPIRE`) — safe
  under concurrent callers
- `TikTokAuth` does NOT persist tokens — encryption and storage are the
  responsibility of the calling layer
- Resource modules are thin wrappers — they add no business logic beyond
  request shaping and never call other resources

## Owners
- domain: integrations
- code: `src/integrations/tiktok/`
- tests: `tests/unit/test_tiktok_*.py`, `tests/integration/test_tiktok_*.py`
- docs: `docs/integrations/tiktok_api/`
