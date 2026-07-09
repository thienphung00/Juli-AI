# Endpoints

Categorized inventory of TikTok Shop Open API endpoints relevant to Juli-AI.
Versioned paths are from official Partner Center docs; **Client path** reflects
the current Python client. Confirm HTTP methods, scopes, and request schemas in
Partner Center **API Reference** before implementation.

**Source:** [Developer Guide](https://partner.tiktokshop.com/docv2/page/tts-developer-guide),
[Java SDK example](https://partner.tiktokshop.com/docv2/page/integrate-java-sdk),
[Partner Center Documents → API Reference](https://partner.tiktokshop.com/docv2/page/),
`backend/integrations/catalog/domain/integrations/tiktok/resources/`.

## Official API Reference categories

Partner Center renders API Reference navigation from
[Documents](https://partner.tiktokshop.com/docv2/page/). Open **API Reference** and use
the category names below as the official source of truth for endpoint paths, scopes, and
schemas.

| Category | Official location |
|----------|-------------------|
| Products | Partner Center Documents → API Reference → Products |
| Promotion | Partner Center Documents → API Reference → Promotion |
| Orders | Partner Center Documents → API Reference → Orders |
| Fulfillment | Partner Center Documents → API Reference → Fulfillment |
| Fulfilled by TikTok (FBT) | Partner Center Documents → API Reference → Fulfilled by TikTok (FBT) |
| Logistics | Partner Center Documents → API Reference → Logistics |
| Return and Refund | Partner Center Documents → API Reference → Return and Refund |
| Finance | Partner Center Documents → API Reference → Finance |
| Analytics | Partner Center Documents → API Reference → Analytics |
| Customer Service | Partner Center Documents → API Reference → Customer Service |
| Customer Engagement | Partner Center Documents → API Reference → Customer Engagement |
| Affiliate Creator | Partner Center Documents → API Reference → Affiliate Creator |
| Affiliate Partner | Partner Center Documents → API Reference → Affiliate Partner |
| Affiliate Seller | Partner Center Documents → API Reference → Affiliate Seller |
| Supply Chain | Partner Center Documents → API Reference → Supply Chain |
| Tools | Partner Center Documents → API Reference → Tools |

---

## Contract discovery (Layer 0 — complete)

Layer 0 contract rows are verified in
[`contract-collection.md`](contract-collection.md). Sanitized response fixtures for the
**minimum Layer 1 read set** are filed under [`samples/`](samples/) (issue #294).

| Layer | Merchant | Endpoints | Status |
|-------|----------|-----------|--------|
| **1 — Production read** | Fujiwa (`7658073774813611784`) | Shops, orders, products, returns, cancellations, inventory search (+ optional affiliate, SPS) | **Minimum set fixtured** — see [`samples/README.md`](samples/README.md) |
| **2 — Sandbox write** | SANDBOX_VN (`7658096633384781588`) | Inventory update, product create/edit, promotion lifecycle, fulfillment split/package/ship | Contracts in `contract-collection.md` §14+; fixtures deferred to Layer 2 slice (#301) |

Regenerate Layer 1 fixtures after contract updates:

```bash
python scripts/extract_tiktok_fixtures.py
```

---

## Vendor → Juli entity mapping

| TikTok entity | Juli model / edge | Notes |
|---------------|-------------------|-------|
| Shop (`id`, `cipher`) | `Shop` | Shop-scoped access everywhere |
| Product / SKU | `Product` | Catalog + Growth Copilot inputs |
| Order / line items | `Order` | Revenue Leakage Detection |
| Return / refund | `Order` status edges | Anomaly detector features |
| Affiliate Creator | `Creator` | Scope-gated; P2 affiliate polling |
| Livestream session | Post-stream summary | **Not** realtime telemetry (forbidden #8) |
| Settlement | Finance signal | `pending` 7–14d; out of P2 core UI |
| Ad / campaign performance | Analytics or Promotion signal | **UNVERIFIED** — confirm under API Reference → Analytics / Promotion |
| Buyer | Masked `buyer_id` only | No PII (#17) |

---

## Authorization

### `/authorization/202309/shops`

| | |
|---|---|
| **Permissions** | Valid shop access token |
| **Pagination** | N/A — returns all authorized shops |
| **Juli use** | OAuth callback provisioning, multi-shop picker |
| **Fixture** | [`samples/authorized-shops-response.json`](samples/authorized-shops-response.json) (`contract-collection.md` §3) |
| **Verified** | `202309` — `GET /authorization/202309/shops`; header `x-tts-access-token` |

**Response:** `shops[]` with `id`, `cipher`, `name`, `region`, `seller_type`.

**Source:** [call-get-authorized-shops](https://partner.tiktokshop.com/docv2/page/call-get-authorized-shops)

---

## Account Health / Performance (Seller)

**Status:** **UNKNOWN** — not confirmed in extracted Partner Center docs.  
**P2-1 gate:** Verify via Partner Center **API Reference** + **API Testing Tool** (login required).  
**Forbidden:** No Seller Center scraping ([Forbidden #9](../architecture/data-sources.md#forbidden--always-non-negotiable)).

### What we want (platform signals)

| Platform signal | Used for | Known to exist in policy docs | Partner API exposure (current) |
|----------------|----------|-------------------------------|--------------------------------|
| Seller VP score | Affiliate enrollment suppression; risk banding | Yes | **UNKNOWN** |
| Seller AHR score | Post-July 2026 health gating | Yes | **UNKNOWN** |
| Seller SFCR / LDR | Proxy operational health | Yes | **UNKNOWN** |
| Balance withholding status | Treat balance as `frozen` | Yes | **UNKNOWN** |
| Violation record events | Alerting + appeal-window tracking | Yes | **UNKNOWN** (webhook catalog not extracted) |

### Degraded-mode contract (Phase 2 — SPS-first)

Juli must **not** assume numeric VP/AHR/CHR scores are exposed. Phase 2 prioritizes
**SPS (Shop Performance Score)** via Partner API when a verified contract exists.
VP/AHR remain platform-policy reference — not a Phase 2 polling gate.

| Tier | `health_data_source` | Inputs | Behavior |
|------|-----------------------|--------|----------|
| 1 (preferred) | `api` | Official SPS or shop-health fields from Partner API | Use exact platform thresholds. |
| 2 (degraded) | `proxy` | Computed proxies from Orders / Products / Affiliate polling | Approximate risk bands; never fabricate VP/AHR/SPS numbers. |
| 3 (explicit gap) | `unavailable` | No trustworthy fields available | UI shows “health score unavailable”; alerts limited to provable signals (e.g. product audit status). |

### Proxy signals we can compute if raw fields exist (UNVERIFIED schemas)

| Proxy | Candidate source endpoint | Notes |
|-------|---------------------------|-------|
| Seller-fault cancellation rate (SFCR proxy) | Orders search/detail | Requires cancel reason / seller-fault markers (schema not extracted). |
| Late dispatch rate (LDR proxy) | Orders search/detail | Requires dispatch timestamps + SLA (schema not extracted). |
| Return/refund rate | Orders + return/refund edges | Partial mapping exists; confirm fields in API Reference. |
| Listing suspension / audit status | Products search/details | `products[].audit.status` already mapped. |
| Affiliate enrollment blocked | Affiliate endpoints errors | Behavioral signal: `PermissionDeniedError (100003)`; not a VP/AHR numeric measure. |

> **Action (P2-1):** Add account-health endpoints + schemas here once verified; update
> `docs/architecture/data-sources.md` + `docs/system-design.md` to reflect confirmed fields.

---

## Token (no request signing)

### `/api/v2/token/get`

Exchange OAuth `auth_code` for tokens. See [authentication.md](authentication.md).

### `/api/v2/token/refresh`

Rotate refresh token. See [authentication.md](authentication.md).

---

## Products

### Official (versioned) — verified Fujiwa contract

| | |
|---|---|
| **Search path** | `POST /product/202309/products/search` |
| **Detail path** | `GET /product/202309/products/{product_id}` |
| **Permissions** | Shop token + `shop_cipher` |
| **Pagination** | `page_token` / `next_page_token` cursor |
| **Fixtures** | [`products-search-response.json`](samples/products-search-response.json), [`products-detail-response.json`](samples/products-detail-response.json) |

**Request body (documented):**

| Field | Type | Required |
|-------|------|----------|
| `status` | string | Optional — `ALL`, `ON_SALE`, `OFF_SALE`, `UNDER_AUDIT` |

**Response `data`:**

| Field | Type |
|-------|------|
| `products[]` | array |
| `products[].id` | string → `Product.external_id` |
| `products[].create_time` | integer |
| `products[].audit.status` | string |
| `next_page_token` | string |

**Source:** [integrate-java-sdk](https://partner.tiktokshop.com/docv2/page/integrate-java-sdk)

### Implemented (`ProductsResource`) — migration note

| Client path (current) | Verified contract | Client API |
|-----------------------|-------------------|------------|
| `/product/202502/products/search` | `POST /product/202309/products/search` | `search`, `search_all` |
| `/product/202502/products/{product_id}` | `GET /product/202309/products/{product_id}` | `get_details(product_id)` |

> **P2-A1 (#297):** migrate `PRODUCT_API_VERSION` from `202502` → `202309` to match verified
> Fujiwa contracts. Response shape is compatible — see fixtures.

**Body:** `status`, optional `update_time_ge` / `update_time_lt` (via Python
`update_time_from` / `update_time_to` aliases). **Query:** `page_size`, `page_token`.

**ETL:** `normalize_product` maps `id` → `product_id`, `audit.status` → `status`.

### Product API — inventory operations (`InventoryResource`)

**Status:** **VERIFIED** in Partner Center under the Product API — **not** a separate
Inventory API family.

**Source:** [Products API overview](https://partner.tiktokshop.com/docv2/page/products-api-overview),
[Search inventory](https://partner.tiktokshop.com/docv2/page/search-inventory-202309),
[Update inventory](https://partner.tiktokshop.com/docv2/page/update-inventory-202309).

| Client path | Client API |
|-------------|------------|
| `/product/202309/inventory/search` | `InventoryResource.search` |
| `/product/202309/products/{product_id}/inventory/update` | `InventoryResource.update` |

**Fixture:** [`inventory-search-response.json`](samples/inventory-search-response.json) (`contract-collection.md` §10).

**Update body:** `skus[]` with `id`, `inventory[]` (`warehouse_id`, `quantity`).

**Phase:** Out of P2 core — `sync_inventory` slated for removal per `map.md` (signals-only ADR-013).

### Product API — listing write workflow (sandbox only)

**Status:** Product create has SANDBOX_VN cURL evidence in
[`contract-collection.md`](contract-collection.md). Other write operations still require
API Testing Tool cURL + response status before implementation. Sequence matches the
Create Hero Product / Optimize Product workflows in `execution_layer.md`.

| Workflow step | Candidate path / operation | Required IDs |
|---------------|----------------------------|--------------|
| Get Category | `GET /product/202309/categories` | — |
| Check Listing Prerequisites | Verifies seller/category eligibility ahead of attribute/brand calls | `category_id` |
| Get Category Attributes | `GET /product/202309/categories/{category_id}/attributes` | `category_id` |
| Get Brands | Resolves `brand_id` for categories where it's required | `category_id` |
| Upload Product Image | `POST /product/202309/images/upload` | image file / URL |
| Get Products SEO Words | `GET /product/202405/products/seo_words` | — |
| Get Recommended Product Title and Description | `GET /product/202405/products/suggestions` | — |
| Create Product | `POST /product/202309/products` | `category_id`, `brand_id` if required, image `uri` |
| Search Product | `POST /product/202309/products/search` | — |
| Get Product | `GET /product/202309/products/{product_id}` | `product_id` |
| Edit Product (partial) | `PUT /product/202309/products/{product_id}` | `product_id` — **method conflict pending sandbox check:** Pass 2 review names this `PUT` ("Partial Edit Product"), while the existing candidate contract (`contract-collection.md` §18) expects `POST` (`editProduct`); confirm the actual method before implementation |
| Update Product Price | `POST /product/202309/products/{product_id}/prices/update` | `product_id`, `sku_id` |
| Activate Product | Product activation/status operation | `product_id` |

Single-SKU and multi-SKU creation share the same Create Product endpoint; multi-SKU
payloads include every SKU, sales attribute, price, and inventory row in one request.

---

## Orders

### Official (versioned) — implemented

| | |
|---|---|
| **Search path** | `POST /order/202309/orders/search` |
| **Detail path** | `GET /order/202507/orders?ids=id1,id2` |
| **Permissions** | Shop token + `shop_cipher` |
| **Pagination** | Query `page_size`, `page_token`; response `next_page_token` |
| **Fixtures** | [`orders-search-response.json`](samples/orders-search-response.json), [`orders-detail-response.json`](samples/orders-detail-response.json) |

**Search body:**

| Field | Type | Notes |
|-------|------|-------|
| `order_status` | string | `UNPAID`, `AWAITING_SHIPMENT`, `CANCELLED`, … |
| `update_time_ge` | integer | Unix — incremental sync lower bound |
| `update_time_lt` | integer | Window end (exclusive) |

**Python API aliases:** `OrdersResource.search(status=…)` maps to `order_status`;
`update_time_from` / `update_time_to` map to `update_time_ge` / `update_time_lt`.

**Response fields (integration mirrors — confirm with live samples):**

| Field | Juli mapping |
|-------|--------------|
| `orders[].id` | `order_id` via `normalize_order` |
| `orders[].user_id` | `buyer_id` (redacted in fixtures) |
| `orders[].payment.total_amount` | `total_amount` |
| `orders[].fulfillment_type` | `FULFILLMENT_BY_SELLER` \| FBT (inferred) — branches Process Order workflow |
| `orders[].shipping_type` | `TIKTOK` \| seller-carrier — branches Ship-by choice within FBS |
| `orders[].cancellation_initiator` | `is_seller_fault` proxy when cancelled |
| `orders[].line_items[]` | `tiktok.order_items.raw` → `OrderItem` table |

**Juli use:** Revenue Leakage Detection — returns, refunds, cancellation patterns.

**Phase:** P2. See [`integration-audit-2026-06.md`](integration-audit-2026-06.md).

---

## Fulfillment

**Status:** **VERIFIED** in Partner Center (Fulfillment API `202309`, Create Packages
`202512`); **not implemented** in Juli client — add `FulfillmentResource` in P2-1.

**Source:** [Fulfillment API overview](https://partner.tiktokshop.com/docv2/page/ship-package-202309),
[Get Package Shipping Document](https://partner.tiktokshop.com/docv2/page/get-package-shipping-document-202309),
[Create Packages](https://partner.tiktokshop.com/docv2/page/create-packages-202512),
[Get Package Detail](https://partner.tiktokshop.com/docv2/page/get-package-detail-202309).

**Scope:** `seller.fulfillment.package.read` / `seller.fulfillment.package.write` (confirm per app).

**Note — Confirm Package Shipment moved to Supply Chain API.** It is no longer a
Fulfillment API operation; see [Supply Chain](#supply-chain) below.

| Juli action (execution layer) | Official operation | Notes |
|-------------------------------|-------------------|-------|
| Validate order (pre-ship) | Order API `/order/202309/orders/search` → `/order/202507/orders?ids=...` | Implemented via `OrdersResource` |
| Create packages | `POST /fulfillment/202512/packages` | Groups order line items; produces `package_id`. `202512` is newer than the `202309` baseline elsewhere in Fulfillment — flag for a sandbox double-check |
| Generate picking list | `GET /fulfillment/202309/packages/{package_id}/shipping_documents` | `document_type=PICK_LIST` |
| Generate shipping labels | `GET /fulfillment/202309/packages/{package_id}/shipping_documents` | `document_type=SHIPPING_LABEL` — same operation as picking list, different `document_type`; not a separate endpoint |
| Ship package | `POST /fulfillment/202309/packages/{package_id}/ship` | Single-package ship |
| Batch ship packages | `POST /fulfillment/202309/packages/ship` | Alternative to single Ship Package for multiple packages in one call |
| Get package detail / monitor shipment status | `GET /fulfillment/202309/packages/{package_id}` | Replaces prior "Monitor Shipment Status" / "Get Package Shipping Info" label — live doc page confirmed at `get-package-detail-202309` |
| Check split eligibility | `GET /fulfillment/202309/orders/split_attributes` | `contract-collection.md` §A-10 |
| Split order | `POST /fulfillment/202309/orders/{order_id}/split` | Sandbox write — `contract-collection.md` Layer 2 |
| Search combinable packages | `GET /fulfillment/202309/combinable_packages/search` | Finds draft packages eligible to combine |
| Combine package | `POST /fulfillment/202309/packages/combine` | Finalizes package combination |
| Uncombine packages | `POST /fulfillment/202309/packages/{package_id}/uncombine` | Sandbox write — `contract-collection.md` Layer 2 |

> Legacy `/api/fulfillment/*` paths appear in third-party SDKs (testing-tool aliases).
> Use versioned `/fulfillment/202309/*` in production client — same migration pattern as Orders.

**Phase:** P2 (Process Order workflow, formerly "Accelerate Order Fulfillment").

---

## Supply Chain

**Status:** **NEW this pass** — added because Confirm Package Shipment was found to live
under the Supply Chain API, not Fulfillment API. **Not implemented** in Juli client.

| Juli action (execution layer) | Official operation | Notes |
|-------------------------------|-------------------|-------|
| Confirm package shipment | `POST /supply_chain/202309/packages/sync` | Moved from Fulfillment API; syncs shipment confirmation after Ship Package / Batch Ship Packages |

**Phase:** P2 (Process Order workflow, step 6).

---

## Returns / Refunds

**Versioning note:** `/return_refund/*` versions are per-operation, not one family
baseline — TikTok versions each release by the endpoints it ships. Search operations
use **`202602`**; approve/reject write operations use **`202309`** (see
`execution_layer.md` 8a/8b/8c). Do not assume the whole Return/Refund family sits on
one version tag.

**Fixtures:** [`returns-search-response.json`](samples/returns-search-response.json),
[`cancellations-search-response.json`](samples/cancellations-search-response.json).

### Implemented (`ReturnsResource`)

| Client path | Client API |
|-------------|------------|
| `/return_refund/202602/returns/search` | `search_returns`, `search_returns_all` |
| `/return_refund/202602/cancellations/search` | `search_cancellations`, `search_cancellations_all` |

**Search body:** `return_status` (returns only), `update_time_ge`, `update_time_lt`.
**Items key:** `return_orders` (returns), `cancellations` (cancellations).

**Seller actions (contract collection required before implementation):**

| Operation | Versioned path | Required ID | Contract |
|-----------|----------------|-------------|----------|
| Approve Cancellation | `POST /return_refund/202309/cancellations/{cancel_id}/approve` | `cancel_id` | `contract-collection.md` §24 (sandbox) |
| Reject Cancellation | `POST /return_refund/202309/cancellations/{cancel_id}/reject` | `cancel_id` | `contract-collection.md` §25 (sandbox) |
| Approve Return | `POST /return_refund/202309/returns/{return_id}/approve` | `return_id` | `contract-collection.md` §26 (sandbox) |
| Reject Return | `POST /return_refund/202309/returns/{return_id}/reject` | `return_id` | `contract-collection.md` §27 (sandbox) |
| Get Decision Eligibility | `GET /return_refund/202601/decision_eligibility` | `return_or_cancel_id` | `contract-collection.md` §A-14 |
| Get Aftersale Eligibility | `GET /return_refund/202602/orders/{order_id}/aftersale_eligibility` | `order_id` | `contract-collection.md` §A-15 |
| Search RMA | `POST /return_refund/202604/rma/search` | — | `contract-collection.md` §A-17 |
| Review Aftersales | `POST /return_refund/202603/aftersales/review` | — | `contract-collection.md` §B-19 (sandbox) |
| Search Aftersales Request | `POST /return_refund/202603/aftersales/search` | — | `contract-collection.md` §A-18 |
| Calculate Refund | `POST /return_refund/202309/returns/{return_id}/calculate` | `return_id` | `contract-collection.md` |
| Get Reject Reasons | `GET /return_refund/202309/reject_reasons` | — | SEA-market requirement (8a/8b/8c) |
| Get Return Records | `GET /return_refund/202309/returns/{return_id}/records` | `return_id` | `contract-collection.md` |

Action calls require an `idempotency_key` query parameter. Verify exact payloads and
seller app scope in Partner Center before enabling execution.

**ETL:** `normalize_return` → `tiktok.returns.raw` → `Return` table. `return_type`
derived from `return_condition` / API `return_type`.

**Sync:** `sync_returns` in `src/apps/cron_jobs/services/polling/sync.py`.

**Workflow mapping:** Prevent Cancellation (8a), Prevent Return (8b), Prevent Refund
(8c) in `execution_layer.md` — the former single "Prevent Order Cancellations" /
"Prevent Product Returns" workflows are now split three ways; see that file for the
full per-step endpoint chain, including the webhook subscriptions each one requires
(Cancellation Status Change, Return Status Change).

---

## Customer Service (Messaging)

**Status:** **VERIFIED** in Partner Center (Customer Service API `202309`); **not implemented**
in Juli client — Phase 3 execution slice.

**Source:** [Customer Service API overview](https://partner.tiktokshop.com/docv2/page/customer-service-api-overview),
[Create conversation](https://partner.tiktokshop.com/docv2/page/create-conversation-202309).

| Juli action (execution layer) | Official operation | Phase |
|-------------------------------|-------------------|-------|
| Contact customers | `create_conversation`, `send_message` | Phase 3 |
| Send product guidance | `send_message` | Phase 3 |
| Answer customer questions | `read_message`, `send_message` | Phase 3 |

> Buyer chat is **Forbidden** for ML training in MVP (`data-sources.md` #17). Execution
> messaging in Phase 3 is operator-initiated seller replies only — not model input.

**Phase:** Phase 3 (Customer Service workflow execution deferred).

---

## Authorization

### Implemented (`AuthorizationResource`)

| Client path | Client API |
|-------------|------------|
| `/authorization/202309/shops` | `list_shops`, `list_all_shops` |

Returns `shops[]` with `id` (tiktok shop id) and `cipher` (`shop_cipher`).

---

## Affiliate — Creators

### Implemented (`CreatorsResource`)

| Client path | Client API |
|-------------|------------|
| `/affiliate_seller/202406/marketplace_creators/search` | `list`, `list_all` |
| `/affiliate_seller/202406/marketplace_creators/{creator_user_id}` | `get(creator_id)` |

**Permissions:** Affiliate scope — `PermissionDeniedError` if seller has not approved.

**Juli mapping:** `Creator` — affiliate cancellation rates for fraud detection.

**Phase:** P2.

---

## Affiliate — Livestreams (post-stream only)

### Implemented (`LivestreamsResource`)

| Client path | Client API |
|-------------|------------|
| `/affiliate_seller/202412/open_collaborations/creator_content_details` | `list`, `list_all`, `get` |

**Query:** `creator_id`, `start_time`, `end_time`, `page_size`, `page_token`.

> Replaces legacy `/api/affiliate/livestreams/*` (testing-tool alias). Maps
> `room_id` / `content_id` → `livestream_id` for ETL compatibility.

**Constraint:** Post-stream summaries only. Realtime in-stream data is **Forbidden** (#8).

**Phase:** Later / out of P2 core per `map.md` pending cleanup (polling worker removal).

---

## Finance — Statements (settlements)

### Implemented (`SettlementsResource`)

| Client path | Client API |
|-------------|------------|
| `/finance/202309/statements` | `list`, `list_all` |

**Query:** `sort_field=statement_time`, `statement_time_ge`, `statement_time_lt`,
`page_size`, `page_token`. Maps `statement_id` → `settlement_id` for ETL.

**Operational rule:** Treat amounts as `pending` for 7–14 days.

**Phase:** Out of P2 core — `sync_settlements` slated for removal per `map.md`.

---

## Analytics / Ads Signals

**Status:** **UNVERIFIED** in TikTok Shop Partner API Reference; **not implemented**
in Juli client.

Use Partner Center **API Reference → Analytics** and **API Reference → Promotion** as
the only source for TikTok Shop analytics, ads, campaign, and promotion surfaces in
this documentation set. Do not add non-Partner API hosts or endpoint paths here unless
they are verified as part of the TikTok Shop Partner API reference.

| Juli signal/action | Partner API Reference category | Status |
|--------------------|--------------------------------|--------|
| Campaign or ads performance | Analytics | **UNVERIFIED** |
| Promotion performance | Promotion / Analytics | **UNVERIFIED** |
| Campaign or promotion execution | Promotion | **UNVERIFIED** |

**Phase:** P2 only after Partner Center API Reference verification.

---

## Promotion

**Status:** **VERIFIED** in Partner Center (Promotion API `202309`); **not implemented**
in Juli client — P2-1 slice.

**Source:** [Promotion API overview](https://partner.tiktokshop.com/docv2/page/promotion-api-overview),
[Deactivate activity](https://partner.tiktokshop.com/docv2/page/deactivate-activity-202309),
[EcomPHP Promotion resource](https://github.com/EcomPHP/tiktokshop-php) (`activities/*` paths).

| Juli action (execution layer) | Official operation | Notes |
|-------------------------------|-------------------|-------|
| Create Activity | `POST /promotion/202309/activities` | `activity_type`: `FIXED_PRICE` \| `DIRECT_DISCOUNT` \| `FLASHSALE` \| `SHIPPING_DISCOUNT` \| `BUY_MORE_SAVE_MORE` |
| Update Activity Product | `POST /promotion/202309/activities/{activity_id}/products` | Attach product/SKU prices |
| Update Activity | `POST /promotion/202309/activities/{activity_id}` | `contract-collection.md` Layer 2 |
| Get Activity | `GET /promotion/202309/activities/{activity_id}` | Search/list not available — use known `activity_id` + webhook #39 |
| Deactivate Activity | `POST /promotion/202309/activities/{activity_id}/deactivate` | Deactivate by activity id |

**Removed — Create/Delete Coupons workflow.** Investigated and confirmed: no `POST`
(create) operation exists for seller-facing coupon creation via the Partner API.
`Create Coupon`, `Search Coupons`, `Get Coupon Detail`, and `Delete / Deactivate Coupon`
are **not implemented and not planned** — coupons appear to be Seller Center-only in the
current API surface. Re-add only if a verified create-coupon contract is found in a
future API version.

**Phase:** P2 (Create Activity / Delete Activity / Update Activity workflows,
Clear Excess Inventory).

---

## Error codes (response envelope)

All endpoints return:

```json
{
  "code": 0,
  "message": "Success",
  "data": { },
  "request_id": "..."
}
```

| Code | Exception | Retry? |
|------|-----------|--------|
| 0 | Success | — |
| 100002 | `AuthenticationError` | Refresh token / re-auth |
| 100003 | `PermissionDeniedError` | Re-consent / scope request |
| 100004 | `ResourceNotFoundError` | No |
| 100005 | `RateLimitError` | Yes — backoff |
| 100006 | `TikTokSystemError` | Yes — transient |

**Source:** `backend/integrations/catalog/domain/integrations/tiktok/exceptions.py`
