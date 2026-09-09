# Research dispatch — Q2 deadline source · Q3 sandbox orders · Q7 batch UX · Q8 exceptions

**[D]** documented (vendor page fetched) · **[D-snip]** official page read only via search snippet · **[D-3P]** confirmed across ≥3 independent third-party SDKs mirroring the schema · **[I]** inferred (blog/forum/reasoning).

**Caveat:** `partner.tiktokshop.com/docv2` is fully JS-rendered and returned no body to any fetch. TikTok API field names below are **[D-3P]**, not first-party. Verify inside Partner Center before coding.

---

## Q2 — Dispatch deadline source and fallback

**TikTok Shop Partner API [D-3P]** — the order carries a *family* of deadlines (Unix seconds), not one:

| Field | Semantics |
|---|---|
| `rts_sla_time` | **The dispatch deadline** — "latest shipping time specified by the platform". Sort the window by this. |
| `tts_sla_time` | Time-to-ship SLA; SDKs treat it as the alternate deadline |
| `shipping_due_time` / `collection_due_time` / `pick_up_cut_off_time` | Hand-over deadline; **carrier collection** cut-off; same-day pickup cut-off |
| `delivery_sla_time` | Delivery deadline — added by TikTok expressly to expose the on-time-delivery-rate calc |
| `delivery_option_required_delivery_time` | Promise implied by the buyer's chosen shipping option |
| `cancel_order_sla_time` | Deadline to respond to a cancellation |
| `rts_time`/`collection_time`/`delivery_time`, `request_cancel_time`, `is_on_hold_order` | Actuals + exception signals on the same object |

Sources: `hsib19/tiktok-shop-sdk`; `easycb/easycb-go`; `fudiwei/…ByteDance` (annotates `rts_sla_time`=RTS SLA, `collection_due_time`=揽货截止, `delivery_sla_time`=发货 SLA); `apsyadira-jubelio/go-marketplace-sdk`; `hotgluexyz/tap-tiktok-shop`.

In the wild **[I]**: `phuongvy201/hmtiktool` resolves the deadline as `rts_sla_time ?? tts_sla_time ?? collection_due_time`; two others map `deadlineAt` straight from `rts_sla_time`, degrading to `create_time`. **Integrators independently converged on Juli's plan.**

Shop-level fallback (VN) **[I]**: status must reach *shipped – chờ lấy hàng* within **72h** (24h recommended). From 2026-06-15 Late Dispatch Rate counts *not-yet-dispatched* orders past SLA, not only late-dispatched; safe <4%, >10% costs AHR points and order limits; >15 days = 2 violation points, >30 = auto-cancel. US: 2 business days, cut-off 23:59 PST. (eimskip.vn/xu-ly-don-hang-tiktok-shop; sellerwix.com/tiktok-shop-fulfillment-policy-2026; seller-us.tiktok.com Fulfillment Policy)

**Amazon SP-API [D]** — `EarliestShipDate`/`LatestShipDate` are a *window*; `LatestShipDate` is the ship-by deadline and explicitly **not** the actual ship date. Derived server-side from the seller's handling-time setting, so the per-order field already encodes the shop rule — no client fallback needed. Late Shipment Rate = ship-confirm after expected ship date, 10-day and 30-day windows, seller-fulfilled only, **must stay under 4%**. (developer-docs.amazon.com Orders API; sellercentral forum 6e9c7ff1…; feedvisor.com/university/late-shipment-rate/)

**Shopee [D-3P]** — the order carries **both halves**: `days_to_ship` (the DTS rule) *and* `ship_by_date` (the computed deadline). Deadline uses the item with the **longest DTS**, excluding non-working days and public holidays. Miss it → Late Shipment Rate (rolling 7 days) → penalty points; never arranged → Shopee **auto-cancels and refunds**. (`wjp-letgo/letgo` orderentity.go; `easycb/easycb-go` shopee/model_order.go; seller.shopee.sg/edu/article/6823)

**Lazada [D-3P]** — no `ship_by`; only `promised_shipping_times` (ISO-8601), a *delivery* promise. Dispatch SLA stays shop-level — weakest of the four. (`easycb/easycb-go` lazada/model_order.go)

**Tools [D/I]** — ShipStation has first-class `Ship By Date` **and** `Deliver By Date`, each a sortable column plus a filter, imported from the marketplace where available; priority views come from *combining filters*, not a fixed urgent tab (help.shipstation.com …360028492892, …360035969712). Sapo, Haravan and Pancake POS sync TikTok orders and offer bulk ops but **no public doc describes a deadline-sorted queue** — they sell channel + inventory consolidation, not SLA triage **[I]**. Open ground for Juli.

**Borrow:** (1) Read the field; don't compute. All three strong platforms bake the shop rule into a server-side per-order timestamp — a local `paid_time + 72h` will disagree on holidays and on longest-DTS. (2) Name the ladder and **record which rung fired**; a computed fallback is a lower-confidence deadline and the confirmation screen should say so. (3) **Two clocks**: `rts_sla_time` (dispatch — what the window batches on) and `collection_due_time` (carrier pickup — missing it still burns the seller). **Contradicting our plan:** "the per-order SLA timestamp" is not one field — a single-column model loses information. Store the family, project one for sorting.

---

## Q3 — Sandbox / test orders for proving a batch-ship write

**TikTok [D, partial]** — sandbox explicitly covers operating the test shop, product CRUD, **get order list, arrange shipment, print labels** — so the write under test is in scope. Partner Center hosts an FAQ literally titled *"How can I create a test order?"* whose body would not render. A **test seller account / test shop must be registered manually**; sandbox is region-limited (UK/ID referenced, separate US guide). **Unresolved [I]:** whether a test order can be created via API or only by manual checkout in the test shop — the "create a test seller account" flow suggests manual. Verify logged in. (partner.tiktokshop.com/doc/faqs/7174708677826386433; /docv2/page/create-test-seller-account; /us/doc/page/275159)

**Amazon [D]** — **static** sandbox pattern-matches params against `x-amzn-api-sandbox.static[...]` and returns canned responses (shape only, no state); **dynamic** (`x-amzn-api-sandbox.dynamic {}`) routes to a stateful backend. Support is per-operation — grep the Swagger model. **There is no `createTestOrder` on Orders.** Programmatic order generation exists only for **Vendor Direct Fulfillment**: Sandbox Test Data API v2021-10-28 `generateOrderScenarios` → `transactionId` → poll `getOrderScenarios` **after ~30–40 minutes**. 5 rps/burst 15; RDTs must be minted in production. (developer-docs.amazon/sp-api/docs/sp-api-sandbox; /reference/generateorderscenarios)

**Shopee [D, thin]** — sandbox host `https://partner.test-stable.shopeemobile.com`, test developer account + bound test shop. **No documented sandbox order-creation endpoint surfaced** → manual placement **[I]**.

**Shopify [D]** — the counter-example: dev stores hold *genuinely real* orders paid with fake money via **Bogus Gateway** (deactivate the real provider, activate it, check out as a customer); documented limit — **draft orders can't use it**. The answer is "make the sandbox hold real orders", not "mock the API". **Walmart [D]** — best shape found: dynamic sandbox + **Simulations API** for partner-controlled *create items → create orders → fulfill → deliver*.

**Borrow:** assume TikTok sandbox **cannot be programmatically seeded** and layer the proof — (a) **contract**: record real order/ship responses once, replay as fixtures (Amazon's static sandbox is exactly this); (b) **dry-run**: run the batch end-to-end but swap the terminal write for a no-op returning the request it *would* have sent, diffed against a golden — for an approval-gated product this is the highest-value gate, because it proves *what the seller is approving*; (c) **sandbox**: manually seed 2–3 long-lived test-shop orders, one per deadline bucket; (d) **canary**: first production run capped at **one seller-selected real order** with the full confirmation UX. **Contradicting our plan:** if CI is expected to create a sandbox order per run, nothing found supports that — Amazon's only programmatic generator takes 30–40 min, which tells you no marketplace treats this as a fast loop.

---

## Q7 — Batch fulfilment confirmation UX

| Platform | Batch mechanism & limit | Shown before the irreversible step | Partial-failure surface |
|---|---|---|---|
| **Amazon** [D-snip/I] | Manage Orders → *Confirm Shipment*; flat-file `Flat.File.ShippingConfirm.xls`; **bulk Buy Shipping** (select → *Get Eligible Services* → rates → buy; purchase auto-confirms) | A **priced rate preview**, not an itemised order list | Async **processing report**: `messagesProcessed/Accepted/Invalid` + per-record `original-record-number, order-id, error-code, error-message`, kept 28 days [D: Feeds API]. Non-atomic. Label void ~24h |
| **Shopee** [D-snip/I] | My Shipment → To Ship → To Process → Mass Ship. Grouped by **shipping channel** + fulfilment type, sorted by **ship-by date**; pickup needs ≥10 paid orders/day | The irreversible choice is **Pickup vs Drop-off** for the whole batch | **No documented per-row batch error report** — unverified. No undo; pressure is auto-cancel at ship-by |
| **TikTok** [D] | Labels **individually or in bulk up to 600 orders**; search caps at 100 order IDs, export 40,000 | **Combine-orders popup** on label creation: recommends merges sharing buyer + address + delivery option, **max 20/package**, seller can **accept, reject, or remove individual orders**. Only truly itemised, editable pre-write confirmation found. Excludes orders with a cancellation request. Amendable only before *Awaiting Collection*; refund approval auto-uncombines | Per-order **"Label rejected"** + carrier reason; bulk **Recreate Label** = retry-failed-only |
| **ShipStation** [D] | Async **Batch**; no documented max | Batch summary only | **"# Errors"** count drilling into each failed order + message (shipment-info / purchasing / notification classes); **Retry All Failures**. Via API a batch reaching *Invalid*/*Completed with Errors* **cannot be reused** — read `/v2/batches/{id}/errors`, fix, create a new batch |
| **Linnworks** [D-snip] | *Do Batch Operation* → **Batch Pilots** | Gated by **Error Prevention**: paid only, items linked, stock sufficient | Non-qualifying orders **stay in the open queue** rather than half-processing — strongest fail-closed pattern found |

Sources: developer-docs.amazon.com/sp-api/docs/feeds-api; sellercentral G201576520; seller.shopee.sg/edu/article/6838; seller-us.tiktok.com knowledge_id 2334828973737741 / 6912884789626626 / 1267080809105194; help.shipstation.com …360026138131; docs.shipstation.com/batch-labels; desktop.linnworks.com/Doc/batch_pilots.

**Cross-cutting.** (1) **Nobody itemises at the irreversible step** — the selection grid *is* the list; confirm shows a choice + count. TikTok's combine popup is the sole exception, and it exists because *merging* is semantically risky, not because writing is. (2) **Grouping is by carrier/channel then pickup-vs-dropoff; deadline is a sort/filter, never a batch boundary.** (3) **Partial failure is the norm; atomicity is never offered** — universal per-row error surface + retry-failed-only. (4) **No order-state undo**, only a carrier-label void window.

**Borrow:** the load-bearing mechanisms are **eligibility gating that drops bad rows *before* the write** (Linnworks-style) and a **durable per-row error artifact with retry-failed-only** after it. **Contradicting our plan:** no platform puts a full itemised list at the confirmation. Juli's context differs — an *agent* proposes the batch rather than the seller hand-selecting it — so count + summary + expandable list, with the deadline bucket named, is the defensible compromise. Batching *by deadline window* is a deliberate divergence from every platform, and it is the product.

## Q8 — Exceptions surfacing

**Amazon [D]** — `OrderStatus` is `Pending|Unshipped|PartiallyShipped|Shipped|Canceled|Unfulfillable|InvoiceUnconfirmed|PendingAvailability`; **there is no "pending cancellation" status**. A buyer request is an orthogonal *flag* on the **OrderItem**: `getOrderItems` returns `BuyerRequestedCancel { IsBuyerRequestedCancel, BuyerCancelReason }`. It bumps `LastUpdateDate`, so date-range polling surfaces it (Reports: `is_buyer_requested_cancellation`); no dedicated notification subtype found — polling is the documented path. Surfaces **inline**: Unshipped tab + "Buyer Requested Cancel" filter + order banner [I]. Buyer self-cancel window is **30 minutes**, not 24h [I]; after ship-confirm the buyer can no longer cancel — **shipping is not blocked, it defeats the request**. Cancellation Rate counts *seller-initiated* cancels only (2.5%). Address changes not permitted post-order; guidance is cancel-and-reorder [I].

**Shopee** — post-arrangement cancellations need seller approval, **1 day** to respond (2 days pre-shipment); no response ⇒ **auto-accept** [I, per-market variable]. Since 2024-11-13 buyers cancel **instantly** before courier handover on Shopee-Supported Logistics [I]. API `handleBuyerCancellation(order_sn, ACCEPT|REJECT)` [D-3P]; `get_cancellation_list` and an `IN_CANCEL` status could **not** be verified — SDK docs list only `UNPAID, READY_TO_SHIP, PROCESSED, SHIPPED, COMPLETED, CANCELLED`. Failed delivery: courier retries 2–3 days, second failure ⇒ cancel + **Return to Sender** [D].

**TikTok [D]** — buyer self-cancel **1 hour** while `Pending`, then it becomes a request. Seller has **24 hours** to upload tracking or approve; **no action ⇒ TikTok auto-approves and refunds**. Auto-cancel if not moved to Awaiting Shipment/Collection within **5–7 business days**. Requests now live **inside Manage Orders**, not a separate page [I]. **Contradicting our plan — the important finding:** Seller University states that **merely shipping without acting on the request still results in the cancellation being approved**. The ship write is **not** documented as refused while a cancellation is pending; the only documented block is on *combining* such orders into a package. Juli must not rely on the platform rejecting the write — the money reverses even though the write succeeds. (seller-us.tiktok.com knowledge_id 6201736389805867; support.edesk.com/tiktok-shop-cancellations-etc). Cancel-endpoint error code seen: `25001021 Reason not match order status` [I].

**OMS tools [D]** — ShipStation has `on_hold` with `holdUntilDate` auto-releasing to Awaiting Shipment (the only deadline-bearing exception found in any tool); exceptions are **inline Order Alerts**, not a queue; **no cancellation-requested state at all**, and held orders can reportedly still be shipped. Linnworks offers **Lock (On-Hold)** and **Park** (unpaid auto-Park) — filter-based, no deadline. Veeqo: `on_hold`, no queue. Sapo/Haravan/KiotViet/Pancake — no retrievable docs (**gap**).

**Borrow:** every *marketplace* attaches a **countdown** to each exception (1h / 24h / 1 day / auto-approve on expiry); **no OMS tool models a deadline or a cancellation-requested state.** That mismatch is the gap Juli fills. So: (1) treat exceptions as *ordered by their own clock* — `cancel_order_sla_time` and `request_cancel_time` sit on the same object as `rts_sla_time`, so one query surfaces both; (2) show exceptions as **inline badges in the window list plus a filter** (what every platform does) rather than a separate queue — a queue is what tools build, and it is exactly why tools lose the deadline; (3) **hard-exclude cancellation-flagged orders from the batch at selection time**, because neither TikTok nor Amazon will refuse the write for you.
