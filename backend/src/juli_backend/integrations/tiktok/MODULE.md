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
  ``ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH``, ``CANCELLATION_SEARCH_PATH``,
  ``FINANCE_STATEMENTS_PATH``, ``INVENTORY_SEARCH_PATH``,
  ``MARKETPLACE_CREATORS_SEARCH_PATH``, ``ORDER_SEARCH_PATH``, ``PRODUCT_SEARCH_PATH``,
  ``PROMOTION_ACTIVITIES_SEARCH_PATH``, ``PROMOTION_COUPONS_SEARCH_PATH``,
  ``RETURN_SEARCH_PATH``,
  ``analytics_shop_live_products_performance_path``,
  ``analytics_shop_performance_per_hour_path``, ``analytics_shop_product_performance_path``,
  ``analytics_shop_sku_performance_path``, ``analytics_shop_video_products_performance_path``,
  ``product_detail_path``, ``promotion_activity_path`` (the last six keyed by the
  shop diagnosis fetch's rate-limit gate, fast track P7-A)
- **Per-order cost reads (fast track P14-C, D24.13)** —
  ``ORDER_PRICE_DETAIL_PATH_TEMPLATE`` (``GET /order/202407/orders/{order_id}/price_detail``,
  scope ``seller.order.info``) and ``FINANCE_ORDER_TRANSACTIONS_PATH_TEMPLATE``
  (``GET /finance/202501/orders/{order_id}/statement_transactions``, scope
  ``seller.finance.info``), the rate-limit bucket keys of
  ``ProductionReadResources.order_costs`` (``OrderCostsResource``:
  ``get_price_detail``, ``get_statement_transactions``; numeric order id only).
  Both GETs are exact entries of the production-read allowlist
- **Optimize Product reads (ADR-090 d.3, ADR-106 Amendments 4–5)** — product
  diagnosis: ``PRODUCT_CATEGORY_VERSION`` (``v2``: all-region shops, every category
  call and the create body), ``PRODUCT_DIAGNOSIS_API_VERSION``, ``PRODUCT_DIAGNOSES_PATH``,
  ``PRODUCT_DIAGNOSE_OPTIMIZE_API_VERSION``, ``PRODUCT_DIAGNOSE_OPTIMIZE_PATH``
  (the POST only scores a proposed listing and writes nothing, so it is on the
  production-read allowlist); seller promotions: ``PROMOTION_ACTIVITIES_SEARCH_PATH``,
  ``PROMOTION_COUPONS_SEARCH_PATH``, ``PROMOTION_COUPON_API_VERSION``,
  ``SEARCH_MAX_PAGE_SIZE``; shop LIVE and video product performance:
  ``ANALYTICS_LIVE_PRODUCTS_API_VERSION``, ``ANALYTICS_SHOP_VIDEOS_LIST_API_VERSION``,
  ``ANALYTICS_SHOP_VIDEOS_PERFORMANCE_PATH``,
  ``analytics_shop_live_products_performance_path``,
  ``analytics_shop_video_products_performance_path``; one video's per-day
  performance (product impressions / clicks, fast track P8-B):
  ``analytics_shop_video_performance_path``
- **Client factories** — ``ClientFactoryConfig``, ``ProductionReadClientFactory``,
  ``ProductionReadResources``, ``SandboxWriteClientFactory``, ``SandboxWriteResources``.
  Since #1995 ``ProductionReadClientFactory.create`` admits **any** merchant auth id
  (rejects an empty one), so a connecting seller's own read credential can build a client;
  every client it returns still carries ``ReadOnlyTransportGuard``. Since P61-G (D71.6) the
  factories decide from the credential, never a configured id: ``ClientFactoryConfig`` carries
  ``credential_capability`` plus the optional DB-derived ``sandbox_merchant_auth_ids`` /
  ``production_merchant_auth_ids``. The production factories refuse a ``sandbox_write``
  credential and any merchant a ``sandbox_write`` row carries; ``SandboxWriteClientFactory``
  requires ``credential_capability == "sandbox_write"`` (unset fails closed) and a non-empty merchant
- **Production write (fast track P61-B, D71.2)** — ``ProductionWriteClientFactory``,
  ``ProductionWriteResources`` (``products`` only). Builds a client for a seller's
  OWN shop; refuses a ``sandbox_write`` credential, a merchant a sandbox row carries, and an empty merchant id. Every client carries ``ProductionWriteGuard``
  (``PRODUCTION_WRITE_ALLOWED_REQUESTS``, ``is_production_write_allowed``: product detail / SEO /
  suggestion GETs, the listing edit PUT, the image upload POST — a strict subset
  of the sandbox allowlist; no price update, no product create, D13). Whether a
  client may be built at all is decided above this layer
  (``services/execution/production_write.py``, the ADR-085 gates)
- ``PRODUCTION_WRITE_ALLOWED_REQUESTS`` — the production write allowlist (P61-B, above)
- ``is_production_write_allowed`` — whether a method/path is on it
- **Merchant isolation** — **no merchant id is configured or hardcoded (P61-G, D71.6, owner
  2026-10-21)**: ``PRODUCTION_AUTH_ID`` / ``SANDBOX_AUTH_ID``, ``TIKTOK_*_MERCHANT_ID``,
  ``MerchantIdNotConfigured``, ``require_*_auth_id``, ``resolve_merchant_context`` and
  ``is_cross_merchant_lookup`` are removed. A merchant's identity is the credential row's own
  ``merchant_authorization_id`` from the connect flow; the sandbox is the ``sandbox_write``
  capability (``core/security``), verified by ``services/tiktok/credential_binding.py``.
  ``TikTokCapability`` (``PRODUCTION_READ`` | ``SANDBOX_WRITE`` | ``SELLER_CONNECT``),
  ``READ_CAPABILITIES`` / ``is_read_capability`` — which capabilities may serve a
  read (#1365): a seller's own capability (``SELLER_CONNECT``) is read-capable
  **for its own shop only** and is never promoted to the production one
  (``PRODUCTION_READ``); the sandbox write capability (``SANDBOX_WRITE``) is not in
  ``READ_CAPABILITIES`` and never reads for another shop. Its one exception is the
  **own-shop read** (fast track P64, D73.2a): ``is_own_shop_sandbox_read`` /
  ``is_own_shop_read_capability`` say yes only when the read is for the credential row's own
  shop, and ``ClientFactoryConfig.own_shop_sandbox_read`` (set by the read paths from that
  check) lets ``ProductionReadClientFactory`` build that one credential a
  ``ReadOnlyTransportGuard`` client (still refused when a production credential carries its
  merchant)
- **Partner reviewer scope (fast track P64, D73)** — ``mark_reviewer_session`` (called by the
  reviewer gate for every reviewer request), ``reviewer_session`` (scoped),
  ``reviewer_session_active``, ``refuse_reviewer_production_write``,
  ``ReviewerProductionWriteRefused``: a context variable; inside it
  ``ProductionWriteClientFactory`` (and, one layer up, the production write resolver and
  ``load_production_write_resources``) refuse — a reviewer writes only through
  ``SandboxWriteClientFactory``
- **Vendor → ingest mapping** — ``analytics_snapshot_key``,
  ``expand_analytics_live_session``, ``expand_analytics_product_detail``,
  ``expand_analytics_product_list_item``, ``expand_analytics_shop_performance``,
  ``expand_analytics_shop_performance_per_hour``, ``expand_analytics_sku_detail``,
  ``expand_analytics_sku_list_item``, ``expand_inventory_search``,
  ``expand_order_line_items``, ``merge_product_analytics_rows`` (fills a
  product-day detail row's missing keys from the A-34 list row, never
  overwriting a value), ``normalize_cancellation``, ``normalize_creator``,
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

Error texts never carry data (D16): a ``TikTokSchemaError`` names the failing field
and the error type, never the rejected input (``schema_error_text``, chained
``from None``), and an HTTP error appends only the envelope's ``code`` and
``request_id`` -- never the body or its message.

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

## Status: LEGACY (fast track P53, D62, 2026-10-18)

Marker only — no behaviour changed, nothing moved or deleted (owner-approved audit cleanup,
`juli-audit/backend.md`). `reactive_refresh.py` has no production importer (2 tests only). ADR-081 row 3 describes a reactive token-refresh layer, so it may be an unwired safety feature rather than dead code: kept, and flagged to the owner rather than deleted.
