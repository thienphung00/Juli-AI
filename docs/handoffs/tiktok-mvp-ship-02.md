# Objective
Ship TikTok MVP wave 2: API endpoints (orders, products, inventory, analytics) and intelligence/scoring module (Issues #37, #34).

# Completed
- PR #59: `feat/issue-37-api-orders-products-inventory` → `main` — Orders, products, inventory, revenue endpoints
- PR #60: `feat/issue-34-livestream-scoring-anomaly` → `main` — Livestream scoring, anomaly detection, retention curves, sentiment
- Issues closed: #37, #34
- Tests: 38 new tests (19 per issue), all green
- No CI configured — validated locally pre-merge

# PR Details

## PR #59 — API: Orders + Products + Inventory + Revenue (#37)
- 10 files changed, +790/-2
- AC1: GET /v1/orders with status/date/product filters, cursor pagination (4 tests)
- AC2: POST /v1/orders/{id}/confirm-shipment with state-machine guard (3 tests)
- AC3: GET /v1/products ranked by revenue with units_sold (3 tests)
- AC4: GET /v1/inventory with velocity indicator per SKU (4 tests)
- AC5: GET /v1/analytics/revenue with daily/weekly/monthly GMV + trend (5 tests)

## PR #60 — Intelligence/Scoring: Livestream grade + anomaly detection (#34)
- 10 files changed, +893/-2
- AC1: score_livestream() → 0–100 weighted grade, comparable across sessions (4 tests)
- AC2: detect_anomalies() → ≥2σ deviations in revenue/orders/viewers (5 tests)
- AC3: get_stream_retention() → minute-by-minute exponential-decay retention curve (4 tests)
- AC4: analyze_comments() → Vietnamese lexicon-based sentiment with NFC normalization (6 tests)

# Decisions
- Both PRs exceeded 400-line guideline but each is a coherent feature unit that resists splitting
- Rebased both branches on updated main before merge (resolved parallel-status.md conflicts only)
- intelligence/scoring module is read-only against data layer — no migrations needed

# Modules
- `api` (extended: 4 new routers + app.py wiring)
- `data` (extended: 3 new model columns, 3 new repo methods)
- `intelligence/scoring` (created: scorer, anomaly, retention, sentiment)

# Interfaces Changed
- `src/api`: GET /v1/orders, POST /v1/orders/{id}/confirm-shipment, GET /v1/products, GET /v1/inventory, GET /v1/analytics/revenue
- `src/data`: Product.revenue, Product.units_sold, InventoryItem.velocity, OrdersRepo.list_filtered(), OrdersRepo.confirm_shipment(), ProductsRepo.list_by_revenue()
- `src/intelligence/scoring`: score_livestream(), detect_anomalies(), get_stream_retention(), analyze_comments()

# Remaining Work
- No post-merge items for these issues
- Remaining unshipped MVP issues from epic #2

# Risks
- No CI pipeline — all validation is manual (pre-merge test runs)
- TikTok OAuth requires sandbox credentials for E2E validation
- datetime.utcnow() deprecation warnings in test_scoring.py (non-blocking, cosmetic)

# Tests
- 38 new tests passing (19 API + 19 scoring)
- No regressions in existing test suite

# Required Context Next Session
- N/A — these features are self-contained and merged

# Bootstrap Prompt
"TikTok MVP wave 2 shipped (API endpoints + intelligence/scoring). See docs/handoffs/tiktok-mvp-ship-02.md."
