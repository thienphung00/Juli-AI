# TikTok Shop Partner API — Full Integration Audit

**Date:** 2026-06-09  
**Evidence:** Deployed client (`src/modules/catalog/domain/integrations/tiktok/`), internal
docs, EcomPHP/tiktok-go-sdk path conventions, TikTok official sample-types repo, third-party
integration guides mirroring Partner Center schemas (Hemi marketplace docs).  
**Gaps:** No `products-response.json`, `orders-response.json`, or similar sample files in
repo — only synthetic parquet under `backtest/revenue_leakage/`. Partner Center pages
require login and could not be scraped here. Field-level claims are tagged by confidence.

**Remediation status (2026-06-09):**

- P0: pagination fix, vendor mapper, Orders migration to `/order/202309/*`
- P0: `ReturnsResource`, OrderItem/Return tables + ETL, `sync_returns`
- P1: header auth (`x-tts-access-token`), `AuthorizationResource`, Products → `/product/202502/*`
- See [`samples/README.md`](samples/README.md) for capture workflow (fixtures still pending)

---

## pre-MVP — Authentication Layer

### Verified

- OAuth authorize URL: `https://services.tiktokshop.com/open/authorize` (`app_key`, `redirect_uri`, `state`)
- Token exchange: `POST /api/v2/token/get` (`grant_type: authorized_code`)
- Token refresh: `POST /api/v2/token/refresh` (`grant_type: refresh_token`)
- Base URL: `https://open-api.tiktokglobalshop.com`
- Signing algorithm matches official SDK (canonical sorted params, HMAC-SHA256 lowercase hex)
- `shop_cipher` required on shop-scoped calls
- Response envelope: `{ code, message, data, request_id }`
- Error code mapping (100002–100006) aligns with docs

### Mismatches

| Issue | Client | Official (202309+ SDK) |
|-------|--------|------------------------|
| Token transport | header on versioned paths; query on `/api/*` | `x-tts-access-token` header |
| Authorized shops | Not implemented | `GET /authorization/202309/shops` |
| Signing tests | `/api/*` paths only | Versioned paths produce different signatures |

**Risk level:** HIGH — wrong token transport + wrong paths → auth failures or silent 100002 on P2 enablement.

---

## Deliverable 1 — Endpoint Verification Report

| Endpoint | Client path | Official path | Status | Confidence | Recommended action |
|----------|-------------|---------------|--------|------------|-------------------|
| Token get | `POST /api/v2/token/get` | Same | VERIFIED | High | Keep |
| Token refresh | `POST /api/v2/token/refresh` | Same | VERIFIED | High | Keep |
| Authorized shops | `GET /authorization/202309/shops` | Same | **MIGRATED** | High | Done 2026-06-09 |
| Products search | `/product/202502/products/search` | Same | **MIGRATED** | High | Done 2026-06-09 |
| Products details | `GET /product/202502/products/{id}` | Same | **MIGRATED** | High | Done 2026-06-09 |
| Orders search | ~~`/api/orders/search`~~ → `/order/202309/orders/search` | `POST /order/202309/orders/search` | **MIGRATED** | High | Done 2026-06-09 |
| Orders detail | ~~`POST /api/orders/detail/query`~~ → `GET /order/202309/orders` | `GET /order/202309/orders?ids=` | **MIGRATED** | High | Done 2026-06-09 |
| Returns search | `POST /return_refund/202309/returns/search` | Same | **MIGRATED** | High | Done 2026-06-09 |
| Cancellations search | `POST /return_refund/202309/cancellations/search` | Same | **MIGRATED** | High | Done 2026-06-09 |
| Creators list | `/affiliate_seller/202406/marketplace_creators/search` | Same | **MIGRATED** | High | Done 2026-06-09 |
| Livestreams | `/affiliate_seller/202412/open_collaborations/creator_content_details` | Same | **MIGRATED** | Med | Replaces legacy alias |
| Inventory (Product API) | ~~`/api/inventory/*`~~ → `/product/202309/inventory/*`, `/product/202309/products/{id}/inventory/update` | **MIGRATED** | High | Done 2026-06-25 — under Product API, not separate Inventory API |
| Settlements | `GET /finance/202309/statements` | Same | **MIGRATED** | High | Done 2026-06-09 |

**Wrapper assessment:** `/api/*` paths appear to be API Testing Tool aliases, not production
surfaces. Treat all remaining `/api/*` paths as non-production until confirmed via Partner
Center with a real shop token.

---

## Deliverable 2 — Request Schema Verification

### Orders search (migrated)

| | Before | After (implemented) |
|---|--------|---------------------|
| Path | `/api/orders/search` | `/order/202309/orders/search` |
| Body | `status`, `update_time_from`, `update_time_to`, `page_size` | `order_status`, `update_time_ge`, `update_time_lt` |
| Query | signing params only | `page_size`, `page_token` |
| Pagination send | body `page_token` | query `page_token` |

### Orders detail (migrated)

| | Before | After |
|---|--------|-------|
| Method | POST | GET |
| Path | `/api/orders/detail/query` | `/order/202309/orders` |
| IDs | body `order_ids` | query `ids` (comma-separated) |

### Products, creators, inventory, settlements

See original audit — still on legacy `/api/*` paths with schema gaps. Products:
`page_size`/`page_token` should be query params; `update_time_from`/`update_time_to`
UNVERIFIED in 202502 body.

---

## Deliverable 3 — Response Schema Verification

### Pagination (fixed 2026-06-09)

| Field | Official | Client (before) | Client (after) |
|-------|----------|-----------------|----------------|
| Response cursor | `next_page_token` | read `page_token` | read `next_page_token` (fallback `page_token`) |
| Request cursor | query `page_token` | body `page_token` | query `page_token` |
| `page_size` | query param | body | query param |

### ETL field mapping (vendor mapper added 2026-06-09)

| API field | ETL expects | Mapper |
|-----------|-------------|--------|
| `id` | `order_id` | `normalize_order` |
| `user_id` | `buyer_id` | `normalize_order` |
| `payment.total_amount` | `total_amount` | `normalize_order` |
| `cancellation_initiator` | `is_seller_fault` | derived when `status=CANCELLED` |

### Still unmapped / missing

- `line_items[]` — not in ETL/DB (no OrderItem table)
- `return_orders[]` — no ReturnsResource
- `vp_score`, `ahr_score`, `withholding_status` — UNAVAILABLE via Partner API
- Response validation — `_handle_response` still returns raw `data` with zero schema checks

---

## Deliverable 4 — Canonical Entity Coverage Matrix

| Entity | Key fields | Status |
|--------|------------|--------|
| Shop | `tiktok_shop_id`, `shop_cipher` | Path verified; fetch not implemented |
| Shop | `vp_score`, `ahr_score`, withholding | UNAVAILABLE (UI only) |
| Order | core fields | VERIFIED; mapper + migration done |
| OrderItem | `sku_id`, `product_id`, `unit_price` | API verified; no DB table |
| Return | all fields | API verified; no client resource or DB table |
| Product | `audit.status` | ETL reads top-level `status` (P1 fix) |
| Creator / Livestream / Settlement | various | Wrong or unverified endpoints |

---

## Deliverable 5 — Revenue Leakage Feasibility

| Feature | Available today? | Blocker |
|---------|------------------|---------|
| Return spike | No | ReturnsResource missing |
| Refund cluster | No | ReturnsResource + ETL |
| Buyer cancellation cluster | Partial | Orders API has fields; mapper helps |
| Item swap detection | Partial | Needs Order + Return resources |
| Empty return detection | No | Field not in API samples |
| Seller fault cancel rate | Partial | Proxy via `cancellation_initiator` in mapper |
| Late dispatch rate | Partial | Timestamps in orders API; formula unbuilt |
| Anomaly ML (Phase 2 MVP Milestone A) | Synthetic only | Not live-API grounded |

---

## Deliverable 6 — Unsupported Assumptions

| Assumption | Risk | Status |
|------------|------|--------|
| `/api/*` paths are production | CRITICAL | Orders migrated; others remain |
| Response pagination token is `page_token` | CRITICAL | **Fixed** |
| `update_time_from` accepted | HIGH | **Fixed** for orders (`update_time_ge`) |
| `is_seller_fault` on orders | HIGH | Proxy in mapper; not API-native |
| Returns embedded in order detail | HIGH | Still false — need ReturnRefund |
| Affiliate `/api/affiliate/*` paths | HIGH | Not migrated |
| Settlements search endpoint | MEDIUM | Not migrated |
| `access_token` in query works everywhere | MEDIUM | Not fixed (P1) |
| ETL field names match API | HIGH | **Fixed** for orders via mapper |
| VP/AHR via Partner API | HIGH | Documented UNAVAILABLE |

---

## Deliverable 7 — Migration Plan

### P0 — Done (2026-06-09)

- [x] `get_all_pages`: read `next_page_token`; send `page_token` in query params
- [x] Orders: migrate to `/order/202309/orders/search` + GET detail
- [x] Vendor mapper: `mapping.normalize_order` + ETL integration

### P0 — Done (2026-06-09, continued)

- [x] `ReturnsResource` + cancellations search
- [x] OrderItem/Return DB tables + ETL channels + `sync_returns`
- [x] Header auth (`x-tts-access-token`) on versioned paths
- [x] `AuthorizationResource`
- [x] Products migrate to `/product/202502/*`

### P0 — Remaining

- [x] Affiliate creators → `affiliate_seller/202406/*`
- [x] Livestreams → `creator_content_details` (202412)
- [x] Finance statements replace settlements search
- [x] Pydantic response models at client boundary (`schemas.py`)
- [ ] Capture real API samples → `docs/tiktok_api/samples/`

### P2 / BLOCKED

- [ ] Affiliate creators → `affiliate_seller/202406/*`
- [ ] Livestreams — block until Partner Center confirms path
- [ ] Finance statements replace settlements search
- [x] Inventory under Product API (`/product/202309/inventory/*`)

---

## Phase 7 — Account Health Availability

**Unavailable via Partner API:** `vp_score`, `ahr_score`, `withholding_status`, `health_score` (SPS is Seller Center UI only).

**Unclear:** `violation_records` (may arrive via webhooks); `shop_performance_value` (Research API, not seller-scoped Partner API).

---

## Success Criteria

| # | Question | Answer |
|---|----------|--------|
| 1 | Official endpoints? | Token + versioned paths |
| 2 | Wrappers or legacy? | `/api/*` = legacy/testing aliases |
| 3 | Valid request schemas? | Orders fixed; others mostly invalid |
| 4 | Verified response fields? | Partial; pagination + order mapping fixed |
| 5 | Canonical fields backed? | ~50% after P0 fixes; returns/health blocked |
| 6 | Revenue Leakage implementable? | Partial after ReturnsResource |
| 7 | Features to disable? | Livestreams, settlements, VP/AHR gating, empty_return ML |
| 8 | Production-safe changes? | Pagination, orders migration, mapper — done |

---

## Recommended Immediate Actions

1. Do not enable P2 polling on remaining `/api/*` paths without Partner Center verification.
2. Capture real API samples via Testing Tool — see [`samples/README.md`](samples/README.md).
3. Add `ReturnsResource` before Revenue Leakage live sync.
4. Add Pydantic response models at client boundary (P1).
5. Migrate `access_token` to header on versioned routes (P1).
