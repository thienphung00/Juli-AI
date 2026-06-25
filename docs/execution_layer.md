# Execution Layer

> **Tier 1 — workflow taxonomy.** Read [`EXECUTION.md`](../EXECUTION.md) first.  
> **Owns:** workflow IDs, action ownership, routing rules. **Does not own:** UI tabs (ADR-014), KPI charts (`visual_layer.md`).

Authoritative workflow → action catalog (ADR-011). Approval-gated execution only.

ML/AI signal generation is never an execution action. Advisory signals from the ML layer
are surfaced in the Visual layer and referenced via `Pre-workflow ML advisory` notes below;
they do not appear as rows in action tables.

## Catalog & rules

Catalog (Catalog expansion is a **separate** workflow from listing edits):

### Update Product Listing

> **Pre-workflow ML advisory:** T9 Pricing Engine (deterministic rule) generates a
> price recommendation (direction + Δ%) before the seller confirms the update.
> Inputs: Revenue by SKU delta, Conversion Rate by Category delta, margin floor config.

| Action | Source | System |
|--------|--------|--------|
| Update Product Title | TikTok | Product API |
| Update Product Description | TikTok | Product API |
| Update Product Images | TikTok | Product API |
| Update Product Price | TikTok | Product API |

### Create New Product Listing

> **Pre-workflow ML advisory:** T9 Pricing Engine (deterministic rule) generates an
> initial price recommendation. Seller reviews before Publish Product.

| Action | Source | System |
|--------|--------|--------|
| Generate Product Title | Juli AI | LLM |
| Generate Product Description | Juli AI | LLM |
| Generate Product Images | Juli AI | User-provided |
| Update Product Price | TikTok | Product API |
| Publish Product | TikTok | Product API |

### Create Product Bundle *(catalog expansion — its own workflow, not part of Update Product Listing)*

> **Pre-workflow ML advisory:** T9 Pricing Engine (deterministic rule) generates a
> bundle price recommendation. Seller reviews before Create Promotion / Publish Bundle.

> **Promotion API verification (Partner Center `202309`):** Bundle go-live uses
> `createActivity` + `updateActivityProduct`. `PromotionResource` not yet in Juli client — P2-1.

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Select Bundle Products | TikTok | Product API | `POST /product/202502/products/search` + detail |
| Generate Bundle Title | Juli AI | LLM | — |
| Generate Bundle Description | Juli AI | LLM | — |
| Generate Bundle Images | Juli AI | User Provided | — |
| Update Bundle Price | TikTok | Product API | Product price edit *(write path P2-1)* |
| Create Promotion | TikTok | Promotion API | `POST …/activities` (`createActivity`) |
| Publish Bundle | TikTok | Promotion API | `updateActivityProduct` — attach SKUs/prices; activity goes `ONGOING` at `begin_time` |

## Ads

> **API verification:** Shop Ads **campaign writes** execute on **TikTok Marketing API v1.3**
> (`business-api.tiktok.com/open_api/v1.3/`) — **not** on the Shop Partner host
> (`open-api.tiktokglobalshop.com`). Requires a separate Marketing API OAuth grant
> (`advertiser_id`). T2 ads **polling** uses the same Marketing API reporting plane.
> `AdsResource` not yet in Juli client — P2-1 slice.
>
> **GMV Max note:** Primary Shop Ads surface for TikTok Shop sellers. `Reduce Bid` applies
> to manual/custom shop ads only; GMV Max uses `campaign/gmv_max/update` and
> `campaign/gmv_max/session/update` for budget instead.

### Increase Ad Budget

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Increase Campaign Budget | TikTok | Marketing API (Shop Ads) | `POST /campaign/update/` or `POST /campaign/gmv_max/update/` |
| Increase Daily Spend Limit | TikTok | Marketing API (Shop Ads) | `POST /adgroup/update/` (budget) or `POST /campaign/gmv_max/session/update/` |
| Activate Campaign | TikTok | Marketing API (Shop Ads) | `POST /campaign/status/update/` (`ENABLE`) or GMV Max create/update |

### Reduce Ad Spend

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Pause Campaign | TikTok | Marketing API (Shop Ads) | `POST /campaign/status/update/` (`DISABLE`) or `POST /adgroup/status/update/` |
| Reduce Bid | TikTok | Marketing API (Shop Ads) | `POST /adgroup/update/` (`bid_price`) — manual ads only; N/A for GMV Max |
| Reallocate Budget | TikTok | Marketing API (Shop Ads) | `POST /adgroup/budget/update/` or budget shift via `adgroup/update` on target ad groups |

## Inventory

> **API verification (Partner Center, Product API `202309`):** Inventory read/write is part of
> the **Product API** — not a separate Inventory API. Search via
> `POST /product/202309/inventory/search`; update via
> `POST /product/202309/products/{product_id}/inventory/update`.
> See [Products API overview](https://partner.tiktokshop.com/docv2/page/products-api-overview) and
> [update inventory](https://partner.tiktokshop.com/docv2/page/update-inventory-202309).

### Replenish via Supplier

> **Pre-workflow ML advisory:** T1 Forecaster (ETS) surfaces the demand risk signal
> on the Stockout Rate KPI. T10 Inventory Reorder Engine (deterministic ROP/EOQ)
> computes the recommended reorder quantity. Seller reviews both signals before
> creating a purchase order.

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Create Purchase Order | Third-Party | Supplier API | — |
| Track Supplier Delivery | Third-Party | Supplier API | — |
| Sync Inventory | TikTok | Product API | `POST …/products/{product_id}/inventory/update` |

### Replenish via ERP

> **Pre-workflow ML advisory:** *(same as Replenish via Supplier — T1 demand signal +
> T10 reorder quantity; seller selects ERP path when stock is self-managed)*

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Create Purchase Request | Third-Party | ERP API | — |
| Confirm Inbound Receipt | Third-Party | ERP API | — |
| Sync Inventory | TikTok | Product API | `POST …/products/{product_id}/inventory/update` |

### Clear Excess Inventory *(bundle creation removed — now its own workflow)*

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Reduce Product Price | TikTok | Product API | Product price edit *(write path P2-1)* |
| Create Promotion | TikTok | Promotion API | `POST …/activities` (`createActivity` — e.g. `FIXED_PRICE`, `PERCENTAGE_OFF`) |

## Operations

### Accelerate Order Fulfillment *(sole owner of Batch Ship Orders)*

> **Pre-workflow ML advisory:** T5 Deadline Rule surfaces the order priority ranking
> on the Orders at SLA Risk KPI (count + priority order). Seller acts on this ranking
> before the workflow begins. Fulfillment Engine label is retired — T5 is the single
> source of truth for order prioritization.

> **API verification (Partner Center, Fulfillment API `202309`):** Order read via Order
> API (`GET /order/202309/orders`). Package create/ship, shipping documents (label +
> pick list), and tracking via Fulfillment API (`Create Packages`, `Ship Package`,
> `Get Package Shipping Document`, `Get Package Detail`, package shipping info).
> `FulfillmentResource` not yet in Juli client — P2-1 slice. Retire **Logistics API**
> as a separate executor label; shipping documents and tracking live under Fulfillment API.

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Validate Order Information | TikTok | Order API | `GET /order/202309/orders` — confirm status, line items, address |
| Generate Picking List | TikTok | Fulfillment API | `Get Package Shipping Document` (`document_type=PICK_LIST`) or `Get Package Detail` |
| Process Order Fulfillment | TikTok | Fulfillment API | `Create Packages` → `Ship Package` (`POST …/packages/{id}/ship`) |
| Generate Shipping Labels | TikTok | Fulfillment API | `Get Package Shipping Document` (`document_type=SHIPPING_LABEL`) |
| Confirm Shipment | TikTok | Fulfillment API | `Ship Package` or `Mark Package As Shipped` |
| Monitor Shipment Status | TikTok | Fulfillment API | `Get Package Shipping Info` / tracking updates |

### Prevent Order Cancellations

> **API verification (Partner Center, Product API `202309`):** Inventory read/write is part of
> the **Product API** — not a separate API family. Search via
> `POST /product/202309/inventory/search`; update via
> `POST /product/202309/products/{product_id}/inventory/update`.
> Inventory change events arrive via the `INVENTORY_UPDATE` webhook.

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Reserve Inventory | TikTok | Product API | `POST …/products/{product_id}/inventory/update` |
| Pause Affected Listings | TikTok | Product API | Product status edit *(write path P2-1)* |
| Sync Inventory | TikTok | Product API | `POST …/products/{product_id}/inventory/update` |
| Monitor Inventory Changes | TikTok | Webhook | `INVENTORY_UPDATE` event |


## Customer Service

> **Execution deferred to Phase 3.** Phase 2 renders Customer Service KPI signals
> (T4 anomaly, T6/T7 returns) and links workflows for advisory routing only — no
> approval-gated execution paths. Action tables below are the **locked Phase 3 target
> taxonomy**; do not stub or implement in Phase 2 code paths.
>
> Partner Center labels buyer messaging as **Customer Service API** (`202309`);
> referred to as Messaging API in seller-facing copy.

### Resolve Recurring Customer Complaints *(Batch Ship Orders removed — belongs to Accelerate Order Fulfillment)*

> **Pre-workflow ML advisory (MVP):** T4 Statistical Anomaly (EWMA / z-score)
> detects complaint-rate anomalies on structured metrics (After-Sales Handling Time,
> Return Request Rate). Complaint text pattern mining and root-cause classification
> are deferred to Phase 3 pending legal text sourcing.

| Action | Source | System |
|--------|--------|--------|
| Contact Customers | TikTok | Customer Service API |
| Update Fulfillment Settings | TikTok | Fulfillment API |
| Pause Affected Listings | TikTok | Product API |
| Escalate Return Case | TikTok | Return/Refund API |
| Monitor Resolution Status | TikTok | Return/Refund API |

### Prevent Product Returns *(listing-edit actions removed — they belong to Update Product Listing)*

> **Pre-workflow ML advisory (MVP):** T6 Return-fraud detector (RandomForestClassifier)
> labels item_swap / empty_return returns, feeding the Return Request Rate by
> SKU/Category KPI via the T7 ranker. Buyer risk scoring and advanced return
> segmentation are deferred to Phase 3. Note: T6 has a known sparse-label gap on
> `empty_return` — report per-class support, never hide behind macro averages.

| Action | Source | System |
|--------|--------|--------|
| Send Product Guidance | TikTok | Customer Service API |
| Answer Customer Questions | TikTok | Customer Service API |
| Offer Resolution Options | TikTok | Return/Refund API |

## Overlap resolution (applied)

| Action | Sole owner | Removed from |
|--------|-----------|--------------|
| Bundle creation | Create Product Bundle | Update Product Listing · Clear Excess Inventory |
| Batch Ship Orders | Accelerate Order Fulfillment | Resolve Recurring Customer Complaints |
| Update Product Description / Images | Update Product Listing | Prevent Product Returns |

## Phase 3 deferrals

The following capabilities are explicitly out of scope for MVP. Do not implement or
stub these in Phase 2 code paths.

| Capability | Removed from workflow | Phase 3 approach |
|---|---|---|
| **Customer Service workflow execution** | Resolve Recurring Customer Complaints · Prevent Product Returns | Locked action tables — Customer Service API (messaging), Return/Refund API (cases/resolutions), Fulfillment API + Product API (corrective splits); no Phase 2 execution stubs |
| Complaint text pattern mining | Resolve Recurring Customer Complaints | Analytics on legal text sources (ADR pending) |
| Root-cause classification | Resolve Recurring Customer Complaints | Seller-fault vs buyer-fault classification model |
| Buyer risk scoring | Prevent Product Returns | ML risk model on buyer behavior features |
| Advanced return segmentation | Prevent Product Returns | Non-fraud return driver classification (extends T6) |
| ML dynamic pricing | Update Product Listing · Create New Product Listing · Create Product Bundle | Elasticity model upgrading T9 deterministic rules |
| ML demand-based reorder | Replenish via Supplier · Replenish via ERP | ML demand forecast upgrading T10 deterministic ROP/EOQ |
