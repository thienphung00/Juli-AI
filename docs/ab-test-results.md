# A/B Experiment Results — KiotViet API Integration

## Executive Summary

Both agents independently produced working, well-structured KiotViet API integrations using the same documentation and requirements, but guided by different skill sets. Both implementations pass all tests and share the same high-level architecture (Facade + Layered), but differ meaningfully in abstraction style, error design, and API ergonomics.

**Agent A** (skills_A) favors **DRY abstraction** — a `BaseResource` template reduces boilerplate across resource modules, and the client serves as a self-contained unit that can be used without the facade.

**Agent B** (skills_B) favors **explicit simplicity** — each resource module is standalone with no shared base class, error mapping is a pure function separated from the transport layer, and the API exposes both single-page and auto-paginated methods for maximum caller control.

| Verdict | Category Winner |
|---------|----------------|
| Architecture | **Agent B** (cleaner separation, dependency inversion) |
| Code Quality | **Tie** (different trade-offs, both high quality) |
| Reliability | **Agent B** (monotonic clock, better invalidation) |
| Testing | **Agent B** (more tests, better organization, faster execution) |
| Developer Experience | **Agent A** (simpler API surface, auto-pagination by default) |
| Performance | **Tie** (negligible differences) |

---

## Quantitative Comparison

| Metric | Agent A | Agent B |
|--------|---------|---------|
| Source files | 12 (10 non-empty) | 10 (8 non-empty) |
| Source LOC | 851 | 868 |
| Functions/classes | 77 | 68 |
| Test files | 9 (4 with tests) | 12 (7 with tests) |
| Test LOC | 948 | 1,010 |
| Tests passing | 54 / 54 | 64 / 64 |
| Test execution time | 0.27s | 0.21s |
| Test-to-source ratio | 1.11 | 1.16 |
| Commits | 3 | 3 |

---

## Detailed Evaluation

### 1. Architecture (Winner: Agent B)

Both implementations share a 3-layer design:

```
Auth Layer → Transport Layer → Domain Layer
```

**Agent A:**
- `KiotVietClient` can construct its own `TokenManager` internally (convenience, but tight coupling)
- `BaseResource` provides a CRUD skeleton via Template Method pattern
- Error mapping (`_raise_for_status`) lives as a static method on the client class
- `_compact()` utility for building query params is duplicated in each resource module

**Agent B:**
- `KiotVietClient` requires `TokenManager` injection (dependency inversion — better testability and flexibility)
- Resources are standalone — no base class, each module is self-contained
- `raise_for_status()` is a pure module-level function in `exceptions.py` with a lookup table, cleanly separated from transport
- `KiotViet` facade provides a `client` property as an escape hatch for custom requests
- Resources accept `**extra` kwargs for forward compatibility with undocumented API params

**Agent B wins** because its dependency inversion and cleaner separation of error mapping make components more independently testable and replaceable.

### 2. Code Quality (Tie)

**Agent A strengths:**
- `BaseResource` reduces ~30 lines of repeated CRUD code across 4 resources
- `_compact()` utility makes parameter building concise and readable
- `list()` auto-paginates by default — fewer decisions for callers
- `MaxRetriesExceededError` carries `last_exception` for debugging
- `RateLimitError` has a dedicated `retry_after` field
- `ValidationError` carries structured `field_errors`

**Agent B strengths:**
- `_STATUS_TO_EXCEPTION` lookup dict is more extensible than an if/elif chain
- `raise_for_status()` is a reusable standalone function, not tied to any class
- Base `KiotVietError` includes `error_code` matching KiotViet's `responseStatus.errorCode`
- Dual `list()` / `list_all()` API gives callers control over pagination behavior
- Resources expose raw API response shape from `list()` (total, pageSize, data)

**Trade-off**: Agent A's `BaseResource` reduces repetition but adds a layer of indirection. Agent B's standalone resources are more explicit but repeat constructor boilerplate. Neither approach is strictly superior.

### 3. Reliability (Winner: Agent B)

| Aspect | Agent A | Agent B |
|--------|---------|---------|
| Thread-safe token management | Double-checked locking | Double-checked locking |
| Token expiry timing | `time.time()` | `time.monotonic()` |
| Token invalidation | Sets `expires_at = 0` | Sets both `token = None` and `expires_at = 0` |
| Renewal buffer | 5 min before expiry | 5 min before expiry |
| Retry backoff | Exponential + proportional jitter (0–50% of delay) | Exponential + fixed jitter (0–0.5s) |
| Max retry delay | 60s | 60s |
| Connection error retry | Yes | Yes |
| 401 auto-reauth | Yes (invalidate + retry) | Yes (invalidate + retry) |
| Non-retryable fail-fast | 400, 403, 404 | 400, 403, 404 |

**Agent B wins** on two technical details:
1. **`time.monotonic()`** — immune to system clock adjustments (NTP jumps, DST). `time.time()` can cause premature or delayed token renewal if the clock is adjusted.
2. **Cleaner invalidation** — sets `_access_token = None` in addition to resetting `expires_at`, making the invalid state unambiguous.

Agent A has a **better jitter strategy** (proportional to delay) which is more effective at preventing thundering herd in distributed deployments, but Agent B's correctness advantages outweigh this.

### 4. Testing (Winner: Agent B)

| Aspect | Agent A | Agent B |
|--------|---------|---------|
| Total tests | 54 | 64 |
| Execution time | 0.27s | 0.21s |
| Unit tests | 20 (auth: 8, client: 12) | 26 (auth: 7, client: 10+1 conn error, exceptions: 9) |
| Integration tests | 9 (all in one file) | 34 (split per resource) |
| Mock API tests | 25 (all in one file) | — (fixtures in separate module) |
| Dedicated exception tests | No | Yes (9 tests) |
| Reusable mock fixtures | No (inline in test file) | Yes (`tests/mocks/kiotviet_responses.py`) |

**Agent B wins** because:
- **19% more tests** covering more edge cases
- **Dedicated exception tests** validate the `raise_for_status` logic and status-to-exception mapping independently
- **Separate test files per resource** — easier to find, run, and maintain
- **Reusable mock fixtures** — response shapes defined once, used across integration tests
- **Faster execution** (0.21s vs 0.27s) despite more tests
- Tests connection errors in retry logic

Agent A's single-file integration/mock test approach works but becomes harder to navigate as the test suite grows.

### 5. Developer Experience (Winner: Agent A)

| Aspect | Agent A | Agent B |
|--------|---------|---------|
| Facade class name | `KiotVietAPI` | `KiotViet` |
| List method behavior | Auto-paginates, returns `list[dict]` | Single page by default, `list_all()` for pagination |
| Get method naming | `get(id)` / `get_by_code(code)` | `get_by_id(id)` / `get_by_code(code)` |
| Standalone client | Yes (creates own TokenManager) | Requires TokenManager |
| Escape hatch for raw requests | Via `api.client` attribute | Via `kv.client` property |
| Forward compatibility | Fixed params only | `**extra` kwargs |

**Agent A wins** because:
- **Simpler default behavior** — `products.list()` returns all products. No need to choose between `list()` and `list_all()`.
- **Shorter call paths** — `api.products.get(123)` vs `kv.products.get_by_id(123)` (though B's naming is more explicit)
- **Self-contained client** — can be used without manually creating a `TokenManager`

Agent B's dual `list()` / `list_all()` API gives more control (access to `total`, `pageSize` metadata from single-page calls), which is better for advanced use cases but adds cognitive load for simple ones.

### 6. Performance (Tie)

Both implementations are architecturally equivalent in performance:
- Both use `requests.Session()` for connection pooling
- Both support lazy pagination via `iter_pages()`
- Both cap page size at 100
- Both retry identically on transient failures

Minor differences:
- Agent A's proportional jitter is slightly better for distributed systems under load
- Agent B's `time.monotonic()` has negligibly less overhead than `time.time()` on some platforms

No meaningful performance difference in practice.

---

## Structural Comparison

### Exception Hierarchy

```
Agent A                              Agent B
───────────────────────              ─────────────────────
KiotVietError                        KiotVietError
├── AuthenticationError              ├── AuthenticationError
├── AuthorizationError               ├── ForbiddenError
├── NotFoundError                    ├── NotFoundError
├── RateLimitError                   ├── ValidationError
│   └── retry_after                  ├── RateLimitError
├── ValidationError                  └── ServerError
│   └── field_errors                 
├── ServerError                      + raise_for_status() function
└── MaxRetriesExceededError          + _STATUS_TO_EXCEPTION lookup dict
    └── last_exception               
```

Agent A's hierarchy is richer (dedicated `MaxRetriesExceededError` with exception chain, `retry_after` on rate limit, `field_errors` on validation). Agent B's is cleaner architecturally (error mapping as a standalone function with a lookup table, `error_code` on every exception).

### Resource Method Comparison

```python
# Agent A — auto-pagination, snake_case params mapped via _compact()
products = api.products.list(include_inventory=True, category_id=5)

# Agent B — explicit pagination choice
page = kv.products.list(include_inventory=True, category_id=5)      # single page
all  = kv.products.list_all(include_inventory=True, category_id=5)  # all pages
```

---

## Lessons Learned

### What Both Got Right
- Layered architecture with clear separation of concerns
- Thread-safe token management with proactive renewal
- Exponential backoff with jitter for retries
- Typed exception hierarchy mapping KiotViet's error format
- Both eager and lazy pagination consumption
- Structured logging throughout
- Environment variable configuration with direct-parameter override

### Skill Set Influence

**Skills A** (Solution Discovery, Context Orchestrator, AI Platform, Engineering Standards, Delivery Pipeline) produced an implementation that prioritizes **developer convenience** — auto-pagination, self-contained components, and DRY base classes reduce the code a caller needs to write.

**Skills B** (Blueprint, Navigator, AI Core, Guardrails, Launchpad) produced an implementation that prioritizes **correctness and separation** — dependency inversion, standalone error mapping, monotonic timing, and explicit API surface give callers maximum control and the system maximum testability.

---

## Recommendation

For a **production system** where correctness, testability, and long-term maintainability are paramount: **Agent B's approach** is stronger due to dependency inversion, `time.monotonic()`, cleaner error separation, and superior test organization.

For a **rapid prototype or internal tool** where developer speed matters most: **Agent A's approach** is preferable due to simpler API surface, auto-pagination defaults, and self-contained components.

The ideal implementation would combine:
- Agent B's architecture (DI, separated `raise_for_status()`, `time.monotonic()`)
- Agent A's DX (auto-pagination by default, `BaseResource`, richer exception metadata)
- Agent B's test organization (per-resource test files, reusable mock fixtures, dedicated exception tests)
