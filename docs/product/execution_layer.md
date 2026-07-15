# Execution Layer

> **Tier 1 — workflow taxonomy.** Read [`EXECUTION.md`](../../EXECUTION.md) first.
> **Owns:** workflow IDs, action ownership, routing rules. **Does not own:** UI tabs (ADR-014), KPI charts (`visual_layer.md`).

Authoritative workflow → action catalog (ADR-011). Approval-gated execution only.

ML/AI signal generation is never an execution action. Advisory signals from the ML layer
are surfaced in the Visual layer and referenced via `Pre-workflow ML advisory` notes below;
they do not appear as rows in action tables.

Endpoint paths and versions are authoritative in
[`contract-collection.md`](../integrations/tiktok_api/contract-collection.md).

---

## Cross-cutting axis 1 — Fulfillment model: FBT vs FBS

Every workflow that touches packages, inventory, or warehouses branches on **who
physically holds and packs the stock**:

- **Fulfillment by Seller (FBS)** — the seller's own warehouse holds stock and packs
  orders. This is the case captured live in `contract-collection.md` (`fulfillment_type:
  "FULFILLMENT_BY_SELLER"`). **This is the only fulfillment_type value observed in live
  data so far** — the FBT-side value/name is inferred from the Fulfilled-by-TikTok (FBT)
  webhook category and Partner API docs.
- **Fulfillment by TikTok (FBT)** — the seller ships inventory *into* a TikTok
  fulfillment center in bulk ahead of time; TikTok's warehouse then picks, packs, and
  hands off every individual order itself. The seller's own `Create Packages` / `Ship
  Package` calls are **not** part of this path — TikTok's warehouse executes them
  internally. The seller-facing surface is inbound-shipment and inventory-sync only,
  driven by the FBT webhook family (#21–24, #58 — see catalog below).

Where a workflow branches on this axis, steps are labeled **`Na` (FBS)** / **`Nb`
(FBT)** with a one-line justification for why the endpoint differs.

## Cross-cutting axis 2 — Ship by TikTok vs Ship by Seller

This is a **sub-case that only exists within FBS** orders (an FBT order is always
shipped through TikTok's own network — there is no seller-side ship-by choice once
TikTok's warehouse owns fulfillment):

- **Ship by TikTok** — seller packs the order, then hands the package to TikTok's
  logistics network (`shipping_type: "TIKTOK"` — observed live on an FBS order in
  `contract-collection.md` §A-4/A-5). TikTok's courier picks up; the seller only needs
  the label/pick-list from `Get Package Shipping Document` and a `Ship Package` call —
  no carrier account of their own is involved.
- **Ship by Seller** — seller packs the order and books their **own** carrier account,
  then reports the resulting tracking number back to TikTok via `self_shipment` (see
  the Batch Ship Packages request schema in `contract-collection.md`). No `Get Package
  Shipping Document` call is needed in this path since TikTok isn't generating the label.

---

## Webhook catalog in use

Full catalog is 68 webhook types; **16 are wired into workflows below**, plus 2 tracked
at the account/platform level outside any single workflow. The rest (~50 — Affiliate
Creator/Seller, Finance beyond invoicing, size chart/translation/combined-listing
metadata, Tokopedia mirror, reserved slots, etc.) are out of scope for Phase 2 and are
not subscribed to.

| # | Webhook | Used in | Role |
|---|---------|---------|------|
| 1 | Order status change | Process Order (5) | Drives the `ON_HOLD → AWAITING_SHIPMENT` trigger — see step 3.5 below |
| 2 | Reverse status update | Request Cancellation (8a), Request Return (8b), Request Refund (8c) | Intake trigger — buyer opened/updated a request needing a seller decision; replaces constant polling of the Search endpoints |
| 3 | Recipient address update | Process Order (5) | Signals an address change after order creation but before/during fulfillment — must re-check before `Create Packages`/`Ship Package` |
| 4 | Package update | Handle Split Package (6) | Confirms a split/combine/other package mutation completed |
| 5 | Product status change | Create Hero Product (1), Optimize Product (2) | Listing review/audit status changed |
| 11 | Cancellation status change | Request Cancellation (8a) | Terminal-state monitor after Approve/Reject |
| 12 | Return status change | Request Return (8b) | Terminal-state monitor after Approve/Reject |
| 21 | Inbound FBT order status change | Replenish Inventory (3b — FBT path) | Tracks the bulk inbound shipment TikTok's warehouse is receiving |
| 24 | FBT inventory update | Replenish Inventory (3b), Request Return (8b — FBT path) | TikTok-side inventory count change for FBT-held stock — the seller does not call `Update Inventory` directly for FBT stock |
| 27 | Inventory status change | Replenish Inventory (3), Clear Excess Inventory (4) | Availability status flips (e.g. in-stock → out-of-stock) |
| 37 | Product audit status change | Create Hero Product (1) | Post-submission audit result, distinct from the general review status in #5 |
| 39 | Activity status change | Create/Update/Delete Activity (7a/7b/7c), Clear Excess Inventory (4) | Promotion lifecycle monitor — replaces the unavailable Search Promotion Activity read |
| 64 | Aftersales Request Status Update | Request Refund (8c) | Status monitor for the aftersales/refund request itself |
| 65 | RMA Status Update | Request Return (8b) | Physical-item tracking monitor — complements/can replace polling Search RMA |
| 67 | Refund Success | Request Refund (8c) | Terminal completion signal for a refund |
| 68 | Inventory changed | Replenish Inventory (3), Clear Excess Inventory (4) | Real-time SKU quantity change from any source (orders, campaigns, manual edit, API, creator allocation) — the general-purpose inventory reconciliation signal |

**Tracked at account/platform level (not tied to one workflow):**

| # | Webhook | Role |
|---|---------|------|
| 6 | Seller deauthorization | Juli AI manages multiple seller shops — this tells the platform a shop has revoked access and its automations must pause |
| 7 | Upcoming authorization expiration | Early warning to trigger a re-auth prompt before a shop's token lapses |

**Deferred to Phase 3 (Customer Service):** #13 New conversation, #14 New message — see
Customer Service section, unchanged from prior scope.

---

## Catalog & rules

### 1. Create Hero Product *(formerly "Create New Product Listing" — endpoint sequence corrected)*

> **Pre-workflow ML advisory:** T9 Pricing Engine (deterministic rule) generates an
> initial price recommendation. Seller reviews before Publish Product.

**Fulfillment model note:** step 5 (SKU inventory/warehouse assignment inside Create
Product) branches FBS vs FBT — an FBS SKU carries the seller's own `warehouse_id`; an
FBT SKU is enrolled against TikTok's fulfillment center instead.

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 1 | Get Category | TikTok | Product API | `GET /product/202309/categories` — resolve `category_id` before requesting attributes |
| 2 | Check Listing Prerequisites | TikTok | Product API | Verifies seller/category eligibility ahead of attribute/brand calls |
| 3 | Get Attributes | TikTok | Product API | `GET /product/202309/categories/{category_id}/attributes` |
| 4 | Get Brands | TikTok | Product API | Resolves `brand_id` for categories where it's required |
| 5 | Upload Product Image | TikTok | Product API | `POST /product/202309/images/upload` — returns image `uri` for `main_images[]` |
| 5.5 | Upload Product File *(optional)* | TikTok | Product API | `POST /product/202309/files/upload` — supporting documents/certificates only when the category requires them; not a replacement for product gallery images |
| 6 | Get Products SEO Words | TikTok | Product API | `GET /product/202405/products/seo_words` |
| 7 | Get Recommended Product Title and Description | TikTok | Product API | `GET /product/202405/products/suggestions` |
| 8 | Create Product | TikTok | Product API | `POST /product/202309/products` — single or multi-SKU payload; SKU warehouse assignment branches FBS/FBT (see note above) |
| 9 | Search Product | TikTok | Product API | `POST /product/202309/products/search` — confirms listing status post-review before the seller promotes it as a "hero" item |
| 9.5 | Monitor Product Status | TikTok | Webhook | **Product status change** (#5) + **Product audit status change** (#37) — async review/audit outcome after step 8, ahead of the seller re-polling with step 9 |

### 2. Optimize Product *(formerly "Update Product Listing" — Get Product → Edit Product → Update Price → description/bundle optimization)*

> **Pre-workflow ML advisory:** T9 Pricing Engine (deterministic rule) generates a
> price recommendation (direction + Δ%) before the seller confirms the update.
> Inputs: Revenue by SKU delta, Conversion Rate by Category delta, margin floor config.

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 1 | Get Product | TikTok | Product API | `GET /product/202309/products/{product_id}` — pulls current title, description, images, price, and attributes; this response feeds steps 2–3 below |
| 2 | Get Products SEO Words | TikTok | Product API | `GET /product/202405/products/seo_words` |
| 3 | Get Recommended Product Title and Description | TikTok | Product API | `GET /product/202405/products/suggestions` |
| 4 | Upload Product Image | TikTok | Product API | `POST /product/202309/images/upload` — only when replacing/adding product images |
| 4.5 | Upload Product File *(optional)* | TikTok | Product API | `POST /product/202309/files/upload` — only when replacing/adding category-required supporting documents |
| 5 | Edit Product (partial) | TikTok | Product API | `PUT /product/202309/products/{product_id}` — Partial Edit Product; a `202509` full-replace variant exists but is not used in this workflow |
| 6 | Update Price | TikTok | Product API | `POST /product/202309/products/{product_id}/prices/update` |
| 6.5 | Monitor Product Status | TikTok | Webhook | **Product status change** (#5) — confirms the edit cleared re-review before the seller treats the listing as live |

---

## Inventory Manage

> **API note:** Inventory read/write is part of the **Product API** — not a
> separate Inventory API. Search via `POST /product/202309/inventory/search`; update
> via `POST /product/202309/products/{product_id}/inventory/update`. **That write path
> is FBS-only** — see workflow 3's FBT branch below for why FBT stock isn't updated the
> same way.

### 3. Replenish Inventory *(formerly two workflows — "Replenish via Supplier" and "Replenish via ERP" — merged into one workflow with two seller-chosen paths; now also split by fulfillment model)*

> **Pre-workflow ML advisory:** T1 Forecaster (ETS) surfaces the demand risk signal on
> the Stockout Rate KPI. T10 Inventory Reorder Engine (deterministic ROP/EOQ) computes
> the recommended reorder quantity. Seller reviews both, then picks a path.

**Fulfillment model note:** replenishment is fundamentally different depending on who
holds the stock. FBS stock is a direct read/write against the seller's own warehouse
row. FBT stock is TikTok-managed — the seller can't just set a quantity; they ship
inventory in bulk into TikTok's fulfillment center and TikTok's system reconciles the
count itself, surfaced only via webhook.

| Step | Action | Source | System | Partner API operation |
|--------|--------|--------|--------|----------------------|
| 1 | Inventory Search | TikTok | Product API | `POST /product/202309/inventory/search` — identify current stock level, either fulfillment model |
| 2a *(FBS)* | Create Purchase Order / Purchase Request (Supplier or ERP path) | Third-Party | Supplier/ERP API | — |
| 2a *(FBS)* | Track Supplier Delivery / Confirm Inbound Receipt | Third-Party | Supplier/ERP API | — |
| 2a *(FBS)* | Update Inventory | TikTok | Product API | `POST /product/202309/products/{product_id}/inventory/update` — direct write against the seller's own warehouse |
| 2b *(FBT)* | Create Inbound Shipment to TikTok fulfillment center | TikTok | Fulfillment/FBT API | See `contract-collection.md` |
| 2b *(FBT)* | Monitor Inbound FBT Order Status | TikTok | Webhook | **Inbound FBT order status change** (#21) — tracks the bulk shipment TikTok is receiving into its warehouse |
| 3 | Monitor Inventory Reconciliation | TikTok | Webhook | **Inventory status change** (#27) + **Inventory changed** (#68) for FBS; **FBT inventory update** (#24) instead of #27/#68 for FBT — the seller-facing signal that the new stock is now sellable |

### 4. Clear Excess Inventory *(refined against Promotion API overview — goal: a full clearance strategy, not a single price cut)*

> **Pre-workflow ML advisory:** T1 Forecaster / stock-age signal flags excess or aging
> SKUs (e.g. sell-through rate below threshold, days-of-inventory above threshold) on
> the Stock Health KPI.

**Why this changed:** the prior version only used a straight price markdown plus one
generic "Create Activity" call. TikTok Shop's promotion tools expose several
clearance-specific levers with different tradeoffs, so the workflow now picks the lever
to match the situation instead of always doing the same thing. **Seller Flash Sale**
(all-channel type) is explicitly positioned for driving conversion on best-selling *or
new* products **as well as stock clearance** — it's the primary lever for fast-moving
clearance, but sellers must meet an eligibility bar to create or edit one (past-order-history
and pricing checks), so the workflow needs an eligibility guard before attempting to
create it.

**Fulfillment model note:** step 6 (zero out floor stock) branches the same way as
workflow 3 — see 6a/6b below.

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 1 | Inventory Search | TikTok | Product API | `POST /product/202309/inventory/search` — identify excess/aging SKUs |
| 2 | Get Activity | TikTok | Promotion API | `GET /promotion/202309/activities/{activity_id}` |
| 3 | Update Price | TikTok | Product API | `POST /product/202309/products/{product_id}/prices/update` — baseline markdown, applied regardless of which promotion lever is chosen |
| 4 | Create Activity (Seller Flash Sale) | TikTok | Promotion API | `POST /promotion/202309/activities` — primary lever, all-channel type, for fast clearance. `activity_type`: `FIXED_PRICE` \| `DIRECT_DISCOUNT` \| `FLASHSALE` \| `SHIPPING_DISCOUNT` \| `BUY_MORE_SAVE_MORE` |
| 5 | Update Activity Product | TikTok | Promotion API | `POST /promotion/202309/activities/{activity_id}/products` — attach the excess SKUs and clearance prices to whichever activity was created in step 4 |
| 5.5 | Monitor Activity Status | TikTok | Webhook | **Activity status change** (#39) — confirms the activity actually went live before relying on it for clearance |
| 6a *(FBS)* | Update Inventory | TikTok | Product API | `POST /product/202309/products/{product_id}/inventory/update` — zero out floor stock once cleared, direct write |
| 6b *(FBT)* | Monitor FBT Inventory Update | TikTok | Webhook | **FBT inventory update** (#24) — TikTok's warehouse reconciles the count once cleared; no seller-side write |
| 7 | Deactivate Activity | TikTok | Promotion API | `POST /promotion/202309/activities/{activity_id}/deactivate` — close out once cleared or expired |

---

## Operations

### 5. Process Order *(formerly "Accelerate Order Fulfillment" — sole owner of Batch Ship Orders; now split by fulfillment model and ship-by choice)*

> **Pre-workflow ML advisory:** T5 Deadline Rule surfaces the order priority ranking on
> the Orders at SLA Risk KPI (count + priority order). Seller acts on this ranking
> before the workflow begins. Fulfillment Engine label is retired — T5 is the single
> source of truth for order prioritization.

> **API note (Partner Center, Orders/Fulfillment/Supply Chain APIs):** Order search
> uses `POST /order/202309/orders/search`; live detail capture currently uses
> `GET /order/202507/orders?ids=...`. Package create/ship, shipping documents (label + pick
> list), and package detail live under Fulfillment API. `FulfillmentResource` not yet in
> Juli client — P2-1 slice. Retire **Logistics API** as a separate executor label;
> shipping documents and package detail live under Fulfillment API. **Confirm Package
> Shipment lives under the Supply Chain API**, not Fulfillment API — see step 7.

**Why Create Packages was added:** the previous table jumped straight from `Get Order
Detail` to `Get Package Shipping Document` / `Ship Package`, both of which require a
`package_id` — but nothing upstream in the table produced one. A package has to be
created (grouping the order's line items) before it can be shipped or have shipping
documents generated for it. Without this step the workflow can't actually execute
end-to-end; it was a real gap, not an optional addition.

**This chain as written (steps 3–7) is the FBS path.** An FBT order never reaches steps
3–7 on the seller's side at all — TikTok's own warehouse creates the package, prints
its own label, and ships it. The seller-facing surface for an FBT order is read-only
status tracking. See 5B below.

#### 5A. Process Order — Fulfillment by Seller (FBS)

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 1 | Get Order List | TikTok | Order API | `POST /order/202309/orders/search` |
| 2 | Get Order Detail | TikTok | Order API | `GET /order/202507/orders?ids=...` |
| 2.5 | Monitor Recipient Address Update | TikTok | Webhook | **Recipient address update** (#3) — if this fires between order detail pull and package creation, re-fetch Get Order Detail before proceeding |
| 3 | WEBHOOK: Order Status Change → `ON_HOLD` to `AWAITING_SHIPMENT` | TikTok | Webhook | **Order status change** (#1) — the production client waits/listens on this webhook and only proceeds to step 4 once the order reaches `AWAITING_SHIPMENT`; it must not attempt `Create Packages`/`Ship Package` while still `ON_HOLD` |
| 4 | Create Packages | TikTok | Fulfillment API | `POST /fulfillment/202512/packages` — groups order line items into a shippable package, producing the `package_id` steps 5–7 depend on |
| 5a *(Ship by TikTok)* | Get Package Shipping Document | TikTok | Fulfillment API | `GET /fulfillment/202309/packages/{package_id}/shipping_documents` (`document_type=PICK_LIST` or `SHIPPING_LABEL`) — needed because TikTok's courier network is doing the physical pickup and expects TikTok-generated labels; also covers the former "Generate Shipping Labels" action, now folded in here |
| 5b *(Ship by Seller)* | *(skip — no TikTok label needed)* | — | — | Seller's own carrier account generates its own label outside the Partner API |
| 6a *(Ship by TikTok)* | Ship Package | TikTok | Fulfillment API | `POST /fulfillment/202309/packages/{package_id}/ship` |
| 6a-alt | Batch Ship Packages | TikTok | Fulfillment API | `POST /fulfillment/202309/packages/ship` — alternative to step 6a for shipping multiple TikTok-logistics packages in one call |
| 6b *(Ship by Seller)* | Batch Ship Packages (with `self_shipment`) | TikTok | Fulfillment API | `POST /fulfillment/202309/packages/ship` — same endpoint as 6a-alt, but the payload carries `self_shipment.tracking_number` + `self_shipment.shipping_provider_id` instead of a TikTok pickup slot; this is how the seller reports their own carrier's tracking number back to TikTok |
| 7 | Confirm Package Shipment | TikTok | **Supply Chain API** | `POST /supply_chain/202309/packages/sync` — moved from Fulfillment API to Supply Chain API; applies to both 6a and 6b outcomes |
| 8 | Get Package Detail | TikTok | Fulfillment API | `GET /fulfillment/202309/packages/{package_id}` — replaces "Monitor Shipment Status" |

#### 5B. Process Order — Fulfillment by TikTok (FBT)

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 1 | Get Order List | TikTok | Order API | `POST /order/202309/orders/search` — same read as 5A; `fulfillment_type` on the returned order distinguishes FBT from FBS |
| 2 | Get Order Detail | TikTok | Order API | `GET /order/202507/orders?ids=...` |
| 3 | Get FBT MCF Order Status | TikTok | Fulfillment/FBT API | Multi-channel-fulfillment order status read — see `contract-collection.md` |
| 4 | Monitor FBT Order Status | TikTok | Webhook | **Get FBT MCF Order Status** webhook (#58) — TikTok's warehouse is packing/shipping; no seller-side Create Packages/Ship Package call exists in this path |
| — | *(No Create Packages, no Get Package Shipping Document, no Ship Package, no Confirm Package Shipment — all internal to TikTok's warehouse)* | — | — | — |

**Removed this pass:** "Generate Shipping Labels" as a standalone action — folded into
step 5a (`Get Package Shipping Document` already handles both document types).

### 6. Handle Split Package *(FBS only)*

**Fulfillment model note:** splitting/combining packages is a seller-warehouse packing
decision. An FBT order is packed entirely inside TikTok's own fulfillment center, so
there is no seller-facing split/combine action for it — this workflow applies to FBS
orders only.

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Get Order Split Attributes | TikTok | Fulfillment API | `GET /fulfillment/202309/orders/split_attributes` |
| Split Orders | TikTok | Fulfillment API | `POST /fulfillment/202309/orders/{order_id}/split` |
| Search Combinable Packages | TikTok | Fulfillment API | `GET /fulfillment/202309/combinable_packages/search` |
| Combine Package | TikTok | Fulfillment API | `POST /fulfillment/202309/packages/combine` |
| Uncombine Packages | TikTok | Fulfillment API | `POST /fulfillment/202309/packages/{package_id}/uncombine` |
| Monitor Package Update | TikTok | Webhook | **Package update** (#4) — confirms the split/combine/uncombine actually landed |

---

## Promotion *(formerly "Marketing & Growth")*

### 7a. Create Activity

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Create Activity | TikTok | Promotion API | `POST /promotion/202309/activities` |
| Update Activity Product | TikTok | Promotion API | `POST /promotion/202309/activities/{activity_id}/products` |
| Monitor Activity Status | TikTok | Webhook | **Activity status change** (#39) — confirms the activity went live |

### 7b. Delete Activity

**Changed this pass:** `Search Activities` is not available (Search Promotion Activity
investigated and not found in the Promotion API Testing Tool). Use **Get Activity**
(by known `activity_id`, already tracked from creation) instead of a search/list call,
supplemented by the lifecycle webhook so the seller doesn't need to poll at all.

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Get Activity | TikTok | Promotion API | `GET /promotion/202309/activities/{activity_id}` |
| Deactivate Activity | TikTok | Promotion API | `POST /promotion/202309/activities/{activity_id}/deactivate` |
| Monitor Activity Status | TikTok | Webhook | **Activity status change** (#39) — confirms deactivation took effect, without an extra Get Activity poll |

### 7c. Update Activity

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Update Activity Product | TikTok | Promotion API | `POST /promotion/202309/activities/{activity_id}` |
| Monitor Activity Status | TikTok | Webhook | **Activity status change** (#39) / **Activity change** (#63) — Activity change (#63) covers configuration edits specifically, distinct from #39's lifecycle-state signal |

---

## Post-sales — split into three simplified workflows

**Return/Refund API versioning:** endpoint versions below are per-operation, not a
single family baseline — TikTok versions each release by the endpoints it ships, so
different operations under `/return_refund/*` legitimately carry different version
tags. `Search Returns` and `Search Cancellations` use **`202602`** (see
[`contract-collection.md`](../integrations/tiktok_api/contract-collection.md)
§A-6–A-7). Approve/Reject
Cancellation and Approve/Reject Return use **`202309`**. `Get Reject Reasons` is
`202309`, cited from a distinct SEA-market changelog entry. The newer endpoints below
(decision eligibility, aftersale eligibility, RMA search, aftersales review/search) are
separate resources with their own version tags.

**Shared design logic across all three (auto-triage, approval as last resort):**
1. **Intake trigger:** the **Reverse status update** webhook (#2) fires the moment a
   buyer opens or updates a cancellation/refund request — this is what populates the
   intake queue in near-real-time, rather than the workflow relying solely on polling
   Search Cancellations/Search Returns/Search Aftersales Request on a timer.
2. Check eligibility (decision window + request eligibility).
3. Run the T6 fraud-risk score where applicable (return/refund only — cancellations
   pre-shipment carry much lower fraud surface).
4. **Auto-approve** clean, in-policy, low-risk requests without a seller tap.
5. **Auto-reject with documented reason** requests that clearly fail eligibility.
6. **Escalate to seller approval only** for the remainder.

> **Pre-workflow ML advisory (8b, 8c only):** T6 Return-fraud detector
> (RandomForestClassifier) labels `item_swap` / `empty_return` risk on incoming return
> and refund requests, feeding the Return Request Rate by SKU/Category KPI via the T7
> ranker. T6 has a known sparse-label gap on `empty_return` — report per-class support,
> never hide behind macro averages. Not applicable to 8a (Cancellation), since
> pre-shipment cancellations don't carry a returned-item fraud signal.

### 8a. Request Cancellation *(formerly "Prevent Order Cancellations" / "Prevent Cancellation")*

Covers buyer- and seller-initiated order cancellations, pre-shipment only. Fulfillment
model doesn't branch this workflow — a pre-shipment cancellation releases a stock hold
the same way whether the order was headed for FBS or FBT fulfillment.

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 0 | Intake trigger | TikTok | Webhook | **Reverse status update** (#2) — buyer/seller opened a cancellation request |
| 1 | Search Cancellations | TikTok | Return/Refund API | `POST /return_refund/202602/cancellations/search` |
| 2 | Get Decision Eligibility | TikTok | Return/Refund API | `GET /return_refund/202601/decision_eligibility` — confirms the seller's decision window hasn't lapsed |
| 3 | Get Reject Reasons | TikTok | Return/Refund API | `GET /return_refund/202309/reject_reasons` — SEA-specific: Partner Center changelog explicitly lists "Get Rejection Reasons before Cancellation or Return Rejection" for SEA markets |
| 4 | Approve Cancellation | TikTok | Return/Refund API | `POST /return_refund/202309/cancellations/{cancel_id}/approve` |
| 4-alt | Reject Cancellation | TikTok | Return/Refund API | `POST /return_refund/202309/cancellations/{cancel_id}/reject` |
| 5 | Monitor Cancellation Status | TikTok | Webhook | **Cancellation status change** (#11) |

**Inventory:** no `Update Inventory` step needed here — a pre-shipment cancellation
releases the order's stock hold automatically, since the item never left the warehouse.
This is the standard reserved-stock pattern. **`Reserve Inventory` has been
removed from this workflow** — investigated and confirmed no such endpoint exists;
inventory holds are a platform-side reservation, not a seller-initiated API write.

### 8b. Request Return *(formerly "Prevent Product Returns" / "Prevent Return" — un-deferred from Customer Service into a live, approval-gated Post-sales workflow)*

Covers post-shipment returns (buyer ships the item back for inspection).

**Fulfillment model note:** step 7 (restock) branches FBS vs FBT — see 7a/7b below.
The rest of the chain (steps 0–6, 8–9) is identical regardless of fulfillment model,
since return intake/eligibility/decision all happen through the same buyer-facing
Return/Refund API surface either way.

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 0 | Intake trigger | TikTok | Webhook | **Reverse status update** (#2) — buyer opened a return request |
| 1 | Search Returns | TikTok | Return/Refund API | `POST /return_refund/202602/returns/search` |
| 2 | Get Aftersale Eligibility | TikTok | Return/Refund API | `GET /return_refund/202602/orders/{order_id}/aftersale_eligibility` — confirms the buyer's request is eligible (30-day window, item condition rules) |
| 3 | Search Return Merchandise Authorization (RMA) | TikTok | Return/Refund API | `POST /return_refund/202604/rma/search` — tracks the physical item coming back before a decision is finalized |
| 3.5 | Monitor RMA Status | TikTok | Webhook | **RMA Status Update** (#65) — event-driven complement to polling step 3 |
| 4 | Review Aftersales | TikTok | Return/Refund API | `POST /return_refund/202603/aftersales/review` — escalation-path review for ambiguous/high-risk cases (high T6 fraud score, e.g. suspected `item_swap`/`empty_return`) before a seller decision |
| 5 | Get Reject Reasons | TikTok | Return/Refund API | `GET /return_refund/202309/reject_reasons` — SEA-market requirement before rejecting a return |
| 6 | Approve Return | TikTok | Return/Refund API | `POST /return_refund/202309/returns/{return_id}/approve` |
| 6-alt | Reject Return | TikTok | Return/Refund API | `POST /return_refund/202309/returns/{return_id}/reject` |
| 7a *(FBS)* | Update Inventory | TikTok | Product API | `POST /product/202309/products/{product_id}/inventory/update` — manual restock after the returned item is physically inspected in the seller's own warehouse; **required**, not automatic |
| 7b *(FBT)* | Monitor FBT Inventory Update | TikTok | Webhook | **FBT inventory update** (#24) — the returned item goes back into TikTok's fulfillment center, which TikTok itself inspects and reconciles; no seller-side Update Inventory call |
| 8 | Get Return Records | TikTok | Return/Refund API | `GET /return_refund/202309/returns/{return_id}/records` |
| 9 | Monitor Return Status | TikTok | Webhook | **Return status change** (#12) |

### 8c. Request Refund *(formerly "Prevent Refund")*

Covers the refund decision itself — separate from return because a refund can happen
**with or without** a physical return (returnless refunds, and the sub-$20
"Refund without Return" auto-program). Fulfillment model doesn't branch this workflow —
see Inventory note below.

| Step | Action | Source | System | Partner API operation |
|---|--------|--------|--------|----------------------|
| 0 | Intake trigger | TikTok | Webhook | **Aftersales Request Status Update** (#64) — a refund request was opened or changed state |
| 1 | Search Aftersales Request | TikTok | Return/Refund API | `POST /return_refund/202603/aftersales/search` |
| 2 | Calculate Refund | TikTok | Return/Refund API | `POST /return_refund/202309/returns/{return_id}/calculate` — refund amount preview (partial vs. full) |
| 3 | Get Reject Reasons | TikTok | Return/Refund API | `GET /return_refund/202309/reject_reasons` |
| 4 | Approve Refund | TikTok | Return/Refund API | `POST /return_refund/202309/returns/{return_id}/approve` — issues the partial or full refund |
| 4-alt | Reject Refund | TikTok | Return/Refund API | `POST /return_refund/202309/returns/{return_id}/reject` — rejects the refund request |
| 5 | Monitor Refund Completion | TikTok | Webhook | **Refund Success** (#67) — terminal completion signal once step 4 finishes processing on TikTok's side |

**Inventory:** no inventory step in 8c — a refund alone (returnless, or the sub-$20
auto-program) doesn't move stock. If the refund is paired with a physical return, the
restock happens in 8b step 7a/7b, not here.

### Inventory auto-update — not uniform across the three workflows

Inventory behavior is **split by workflow, and within 8b also by fulfillment model:**

- **8a Cancellation:** stock was only ever *held*, not removed from sellable inventory
  (the item never shipped) — the hold releases automatically when TikTok Shop processes
  the cancellation. **No `Update Inventory` call needed**, regardless of FBS/FBT.
- **8b Return, FBS:** **not automatic**. Walking through the actual TikTok Seller
  Center return flow: after accepting a returned package, the seller has to check the
  item's condition and manually add the quantity back — the platform doesn't assume a
  returned item is automatically resellable (it could be damaged). This is why 8b step 7a
  (`Update Inventory`) is required, not optional.
- **8b Return, FBT:** the returned item physically goes back into TikTok's own
  fulfillment center, which handles its own inspection/reconciliation — surfaced only via
  the FBT inventory update webhook (step 7b), not a seller-initiated write.
- **8c Refund:** no inventory to update — the item either never left the buyer's hands
  in the returnless case, or (if paired with a return) the restock already happened in 8b.

---

## Customer Service — Post-sales Solutions *(taxonomy refresh only — still deferred to Phase 3)*

> **Execution deferred to Phase 3 — unchanged.** Phase 2 renders Customer Service KPI
> signals (T4 anomaly, T6/T7 returns) and links workflows for advisory routing only —
> no approval-gated execution paths. Only naming/grouping was refreshed — no operations
> added or removed. **Note the scope change:** return/refund/cancellation handling that
> used to live here as "Prevent Product Returns" has moved to the live, approval-gated
> Post-sales workflows (8a/8b/8c) above. Only buyer-messaging / complaint-narrative
> capabilities remain deferred here.
>
> Partner Center labels buyer messaging as **Customer Service API** (`202309`);
> referred to as Messaging API in seller-facing copy. Relevant webhooks (deferred, not
> wired into any Phase 2 workflow): **New conversation** (#13), **New message** (#14).

### Resolve Recurring Customer Complaints

> **Pre-workflow ML advisory (MVP):** T4 Statistical Anomaly (EWMA / z-score) detects
> complaint-rate anomalies on structured metrics (After-Sales Handling Time, Return
> Request Rate). Complaint text pattern mining and root-cause classification are
> deferred to Phase 3 pending legal text sourcing.

---

## Overlap resolution (applied)

- **Batch Ship Orders** — sole owner is **Process Order** (5A step 6a-alt / 6b, Batch Ship Packages). Not duplicated elsewhere.
- **Listing-edit actions** (title/description/image/price) — sole owner is **Optimize Product**. Post-sales and Customer Service workflows never edit listing content directly.
- **Inventory writes** — every FBS workflow that changes sellable quantity funnels through the single Product API `Update Inventory` operation; FBT stock is never written to directly by the seller, only observed via webhook. No workflow maintains its own parallel inventory-mutation path.
- **Return/Refund/Cancellation** — sole owner is Post-sales 8a/8b/8c. Customer Service's `Escalate Return Case` reuses the same Return/Refund API operation rather than a parallel one.
- **FBT seller-facing surface** — sole owner is the `Nb`/FBT branch of whichever workflow it appears in (5B, 3b, 4-6b, 8b-7b). No separate "FBT workflow" exists outside these branches; FBT is a fulfillment-model attribute of the same workflows, not a distinct catalog entry.

## Phase 3 deferrals

The following capabilities are explicitly out of scope for MVP. Do not implement or
stub these in Phase 2 code paths.

| Capability | Removed from workflow | Phase 3 approach |
|---|---|---|
| **Customer Service buyer-messaging execution** | Resolve Recurring Customer Complaints | Locked action table — Customer Service API (messaging), Return/Refund API (escalation reuse), Fulfillment API + Product API (corrective splits); no Phase 2 execution stubs |
| Complaint text pattern mining | Resolve Recurring Customer Complaints | Analytics on legal text sources (ADR pending) |
| Root-cause classification | Resolve Recurring Customer Complaints | Seller-fault vs buyer-fault classification model |
| Buyer risk scoring | Request Return (8b) | ML risk model on buyer behavior features |
| Advanced return segmentation | Request Return (8b) | Non-fraud return driver classification (extends T6) |
| ML dynamic pricing | Optimize Product · Create Hero Product | Elasticity model upgrading T9 deterministic rules |
| ML demand-based reorder | Replenish Inventory | ML demand forecast upgrading T10 deterministic ROP/EOQ |
| FBT inbound-shipment creation API | Replenish Inventory (3b) | Path not yet captured — needed before FBT replenishment can be automated end-to-end |
| Affiliate/Creator webhook-driven workflows | — | Out of scope for Phase 2; webhooks #17, #20, #33, #55, #56, #59 not subscribed |

### Deferred actions

| Action | Source | System | Partner API operation |
|--------|--------|--------|----------------------|
| Contact Customers | TikTok | Customer Service API | `create_conversation` / `send_message` |
| Update Fulfillment Settings | TikTok | Fulfillment API | Fulfillment settings/package operation |
| Pause Affected Listings | TikTok | Product API | Product status edit/deactivate operation |
| Escalate Return Case | TikTok | Return/Refund API | `POST /return_refund/202309/returns/{return_id}/reject` or appeal/escalation op |
| Monitor Resolution Status | TikTok | Return/Refund API | `POST /return_refund/202602/returns/search` |

**Note:** Request Return (8b) and Request Cancellation (8a) themselves are **not**
deferred — they are live, approval-gated Phase 2 workflows (auto-triage + seller
approval as last resort). Only the buyer-risk-scoring/segmentation *ML upgrades* to
those workflows are deferred, same as the deterministic-rule-to-ML upgrade pattern used
for T9/T10 elsewhere in this table.
