# KiotViet API Integration — Implementation Notes

## Architecture Overview

```
KiotViet (facade)
  ├── TokenManager          (auth.py)      — OAuth 2.0 token lifecycle
  ├── KiotVietClient        (client.py)    — HTTP engine with retry + pagination
  └── Resource modules
       ├── ProductsResource  (resources/products.py)
       ├── OrdersResource    (resources/orders.py)
       ├── CustomersResource (resources/customers.py)
       └── InventoryResource (resources/inventory.py)
```

The top-level `KiotViet` class wires everything together and exposes a
clean facade:  `kv.products.list_all()`, `kv.orders.get_by_id(123)`, etc.

## Key Design Decisions

### 1. Layered Separation of Concerns

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Auth | `auth.py` | Token acquisition, proactive renewal, thread safety |
| Transport | `client.py` | HTTP requests, retry logic, pagination, error mapping |
| Domain | `resources/*.py` | Endpoint-specific parameters and convenience methods |
| Errors | `exceptions.py` | Typed exception hierarchy mapped from HTTP status codes |

Each layer has a single responsibility and can be tested in isolation.

### 2. Thread-Safe Token Management

`TokenManager` uses a threading lock with a double-check pattern:
- First check: fast path without lock acquisition
- On miss: acquire lock, re-check, then authenticate
- `invalidate()` forces the next call to re-authenticate (used by 401 handling)

Tokens are renewed 5 minutes before expiry (`RENEWAL_BUFFER_SECONDS = 300`) to
avoid failures mid-request.

### 3. Retry Strategy

The client implements retries with exponential backoff + jitter:

- **Base delay**: 1 second
- **Max delay**: 60 seconds
- **Max retries**: 5 (configurable)
- **Jitter**: 0–0.5s random to prevent thundering herd
- **Retryable conditions**: HTTP 429, HTTP 5xx, network errors
- **Special case**: HTTP 401 triggers token invalidation + retry (no backoff)

Non-retryable errors (400, 403, 404) fail immediately.

### 4. Error Normalization

All KiotViet API errors are mapped to a typed exception hierarchy:

```
KiotVietError (base)
  ├── AuthenticationError  (401)
  ├── ForbiddenError       (403)
  ├── NotFoundError        (404)
  ├── ValidationError      (400)
  ├── RateLimitError       (429)
  └── ServerError          (5xx)
```

Each exception carries `status_code`, `error_code`, and structured `errors[]`
extracted from KiotViet's `responseStatus` payload.

### 5. Pagination

KiotViet uses offset-based pagination (`currentItem` + `pageSize`).
The client provides:

- `get_all(path, params)` — collects all pages into a list
- `iter_pages(path, params)` — yields records lazily (memory-efficient)

Both respect `MAX_PAGE_SIZE = 100`.

### 6. Resource Modules — Thin Wrappers

Resource modules translate Pythonic keyword arguments to KiotViet query
parameters. They intentionally stay thin:

- No business logic
- No caching
- No transformation of response data

This keeps the integration layer as a faithful mirror of the API,
leaving business concerns to the calling layer.

## Environment Variables

| Variable | Description |
|----------|-------------|
| `KIOTVIET_CLIENT_ID` | OAuth client ID |
| `KIOTVIET_CLIENT_SECRET` | OAuth client secret |
| `KIOTVIET_RETAILER` | Store name for the `Retailer` header |

All three can be overridden by passing arguments directly to `KiotViet()`.

## Test Strategy

| Suite | Directory | Coverage |
|-------|-----------|----------|
| Unit tests | `tests/unit/` | Auth token lifecycle, retry logic, error mapping, pagination |
| Integration tests | `tests/integration/` | All resource methods against mock HTTP server |
| Mock fixtures | `tests/mocks/` | Reusable response payloads for all endpoints |

All HTTP is mocked via the `responses` library — no real API calls in tests.

## Dependencies

- `requests` — HTTP client
- `python-dotenv` — env-var loading convenience
- `pytest` + `pytest-mock` + `responses` — test framework and mocking
