# Module: integrations/tiktok

## Responsibility
Provides a typed, signed, rate-limited HTTP client for the TikTok Shop Partner
API plus OAuth lifecycle management.

## Public Interface

### Authentication (`auth.py`)
- `TikTokAuth(app_key, app_secret, base_url)` — OAuth lifecycle manager
- `TikTokAuth.generate_auth_url(redirect_uri, state) -> str` — build the seller
  consent URL
- `TikTokAuth.exchange_code(auth_code) -> dict` — auth code → access + refresh
  tokens
- `TikTokAuth.refresh_access_token(refresh_token) -> dict` — rotate tokens

### HTTP Client (`client.py`)
- `TikTokClient(app_key, app_secret, access_token, base_url, shop_cipher,
  timeout)` — low-level signed HTTP client
- `TikTokClient.get(path, params) -> dict` — signed GET, returns `data` payload
- `TikTokClient.post(path, body, params) -> dict` — signed POST, returns `data`
  payload
- `TikTokClient.put(path, body, params) -> dict` — signed PUT, returns `data`
  payload
- `TikTokClient.get_all_pages(path, body, items_key, page_size) -> list[dict]`
  — auto-paginate a cursor-based POST endpoint

### Request Signing (`signing.py`)
- `sign_request(app_secret, path, params, body="") -> str` — compute the
  HMAC-SHA256 `sign` parameter required on every TikTok API call

### Rate Limiting (`rate_limiter.py`)
- `RateLimiter(redis_client)` — Redis-backed token bucket
- `RateLimiter.acquire(app_id, shop_id, endpoint, max_requests, window_seconds)
  -> bool` — atomically consume one token; `False` when exhausted
- `RateLimiter.time_until_reset(app_id, shop_id, endpoint) -> int` — seconds
  until the bucket refills

### Resources (`resources/`)
- `OrdersResource(client)` — search / search_all / get_details
- `ProductsResource(client)` — search / search_all / get_details / create / edit
- `InventoryResource(client)` — Product API inventory search / update
- `FulfillmentResource(client)` — combine / ship / batch_ship / split / uncombine / confirm_shipment
- `CreatorsResource(client)` — list / list_all / get (Affiliate API, requires
  per-seller scope approval)
- `LivestreamsResource(client)` — list / list_all / get (post-stream summaries
  only, no realtime telemetry)
- `SettlementsResource(client)` — list / list_all (date-range filtering,
  net amounts after deductions; values pending 7–14 days before confirming)
- `strip_nones(d) -> dict` — utility to drop `None` values before sending

### Exceptions (`exceptions.py`)
- `TikTokAPIError(code, message, request_id)` — base
- `AuthenticationError` — token expired / invalid signature (code 100002)
- `PermissionDeniedError` — missing scope (code 100003)
- `ResourceNotFoundError` — entity missing (code 100004)
- `RateLimitError` — throttled (code 100005)
- `TikTokSystemError` — transient server failure, safe to retry (code 100006)
- `error_from_response(response_dict) -> TikTokAPIError | None` — maps a raw
  TikTok response to the typed exception (or `None` on success)

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
