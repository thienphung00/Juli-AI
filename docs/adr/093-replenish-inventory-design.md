# ADR-093: Replenish Inventory — an inventory-risk forecaster with a human-relayed supplier and a stock-health measure

**Status:** Proposed
**Date:** 2026-09-05
**Deciders:** grill-with-docs (Architect) with user

**Amends:** [`execution_layer.md`](../product/execution_layer.md) §3 (Replenish Inventory —
the Supplier/ERP "path" becomes a human-relayed attested report; the FBT branch stays deferred);
[ADR-077](077-incremental-impact-measurement.md) for this workflow only — the impact reading is
a **stock-health series**, not a revenue reading.
**Builds on:** [ADR-091](091-clear-excess-inventory-design.md) (`waiting_external`, the
intervention guard, TikTok's days-of-supply formula), [ADR-092](092-process-order-dispatch-design.md)
(batch confirmation, re-verify before the write, subset-only execution),
[ADR-075](075-agent-approval-gate-and-security-prerequisites.md) (decision request, params-hash
consent), [ADR-055](055-decision-plan-review.md) d.19 (agent-proposed value).
**Introduces:** the **attested report** as a consent moment — a confirmation whose bound
parameters are seller-supplied, not model-supplied — and the **event outcome store** that
calibrates the seller's own uplift for the next event.
**Scope:** W10, [`PLAN.md` §14](../product/agent-workflow-execution/PLAN.md) design-order item 4.
Owner framing (2026-09-04): this workflow's main functionality is to **analyze and forecast the
inventory spike for a mega sale, interact with the supplier, and update stock** — replenishment is
one of its levers, inventory-risk forecasting is its job.

> **Amendment 2026-09-08 (supply intake, owner decision).** Decision 2's supplier relay is
> not a form — it is an **intake pipe with a pluggable source**, and v1 plugs exactly one
> source into it. Evidence for the shape:
> [`research/supplier-handling-vietnam-tools.md`](../product/agent-workflow-execution/research/supplier-handling-vietnam-tools.md)
> (eight VN tools: no supplier API anywhere, supplier is a contact record, the bridges are
> e-invoice pull, emailed PO, Excel import, barcode scan, photo/OCR) and
> [`research/supplier-connectivity-global-tools.md`](../product/agent-workflow-execution/research/supplier-connectivity-global-tools.md)
> (ten global tools: acknowledgement is a status a human sets, receipt is a separate entity
> from the purchase order, document capture always drafts and never posts).
>
> **(a) Every report is a supply event.** Each "ordered" and "received" report of d.2 is
> stored as a **supply event** carrying `source` (v1: `seller_form` only), the parsed
> fields, a **per-field confidence**, a reference to the source document when one exists,
> and `confirmed_by` / `confirmed_at`. ADR-075's params hash binds the **confirmed** values,
> never the parsed ones — a parse is a proposal, a confirmation is the consent. The stock
> delta write of d.2 consumes **confirmed receipts only**. This is what makes a second
> source additive rather than a re-design: a photo or an e-invoice line enters the same
> event with a different `source` and a lower confidence, and still cannot move stock until
> a human confirms it.
>
> **(b) Two records, not one.** A **purchase record** carries the state machine
> `draft → sent → acknowledged (as-is | with-changes | rejected) → partially_received →
> received → closed`; a **receipt record** is written **per delivery**, with **accepted**
> and **short** per line. Retrofitting multi-shipment onto a `qty_received` column is the
> documented trap (global research §2); the acknowledgement triple is EDI 855's and Odoo's,
> reachable in v1 by the seller setting it after reading a chat message.
>
> **(c) A supplier record per shop.** A **supplier** entity — stable id, name, lead time,
> contact fields, and a **supplier-SKU → Juli-SKU alias map** that starts empty and fills
> as receipts are confirmed — replaces d.2's "supplier and lead time remembered from the
> seller's prior runs" and the `supplier` card field's payload-level memory. Every tool
> surveyed models the supplier this way, and the alias map is the join a v2 document source
> needs on its first line.
>
> **(d) `supplier` joins the sanitiser's provenance vocabulary.** ADR-070 d.3's source
> roles gain `supplier`, handled **untrusted like `vendor`** — a supplier's message,
> delivery note or invoice line is data, never an instruction, and never a fact.
>
> **(e) v2 sources, in evidence order.** **Photo/OCR of the delivery note** first — it is
> also how a Zalo message arrives, since the seller forwards the image; then the **tax
> authority's e-invoice feed** (the KiotViet "Hóa đơn đầu vào" / MISA INBOT pattern, the
> highest-coverage supplier traffic found in VN); then **Excel import** of PO lines and
> delivery notes. **No per-supplier API** is in scope at any version — none of the eighteen
> tools surveyed exposes one, and the long tail is chat, email and PDF. **Zalo Notification
> Service is customer-only** by Zalo's own template rules (no partner/supplier purpose tag)
> and is **not a supplier channel**.
>
> **(f) The v1 seller experience is unchanged.** The report form still creates *and*
> confirms the event in one tap; the pipe is behind it. Nothing in Stage C/D's step table
> changes for v1.

## Context

**TikTok already computes the run-rate number.** Quản lý hàng tồn kho publishes a 30-day sales
forecast, **Số lượng bổ sung hàng đề xuất** = forecast × period − available, and **Số ngày cung
ứng**, with alerts by quantity or days of supply and an exportable replenishment list
([`seller-journeys/product.md`](../product/agent-workflow-execution/seller-journeys/product.md) §C).
Inventory Search returns quantities only — `available_quantity` and `committed_quantity` — so Juli
computes days of supply with TikTok's formula (ADR-091 d.1). What TikTok does **not** compute is an
**event uplift**: the 30-day forecast is a run rate, and a mega sale is a step.

**Stock locks at order placement, not at add-to-cart.** The dashboard's buckets are *Hiện có*
(sellable), *Đã khóa cho chiến dịch*, *Nhà sáng tạo*, and *Đã khóa vì đã chốt đơn* — "the customer
placed an order but the goods have not left the warehouse"
(`academy_documents/feature-guides/seller/products/quan-ly-hang-ton-kho-6837780085163777.md:47-49`).
The Partner API exposes the same split as `available_quantity` / `committed_quantity`
(`inventory-search-202309.md:219-225`). No page in either corpus describes a cart-level lock. The
owner's observed pain — "the seller has to manually add the item back" — is the **auto-restock
toggle** (*Tự động về lại hàng*): ON returns stock on customer cancellation, payment timeout and
system auto-cancel (never on a seller cancel for out-of-stock); OFF means the seller restores stock
by hand or from an ERP (`:114-122`). TikTok recommends OFF for multi-platform and ERP sellers —
exactly the sellers who cannot hand-restore stock during a sale. The toggle is configurable per SKU
through **Update Stock Operation Settings** (`POST /product/202604/inventory/operation/settings`,
scope `seller.product.basic`), documented, **not captured live**.

**A stock write can be silently invalidated three ways** (product journey §C, §F.3): the
auto-restock state, the **Luôn sẵn hàng** committed quantity (available must exceed locked; only
three auto-unlocks per seller), and multi-warehouse allocation, which is a per-warehouse popup
rather than one number. **No supplier or ERP surface exists** anywhere — in Seller Center, in the
Partner API, or in Juli's code.

**During a mega sale the pain has three parts Juli can see:** committed stock that cancels and never
returns because auto-restock is off; campaign-locked stock that is invisible to Inventory Search
until the sale ends (`process-order-actors.md`, contract gap); and the forecast gap between a
run-rate and an event.

## Decisions

> **Amendment 2026-09-05 (platform research, [`research/receiving-forms-and-stock-targets.md`](../product/agent-workflow-execution/research/receiving-forms-and-stock-targets.md)).**
> Decision 2's single write is a **delta** — the accepted quantity applied to a freshly re-read
> marketplace level immediately before the call — never an absolute quantity computed when the
> form rendered. Sapo's documented failure mode is exactly the blind overwrite of a marketplace-side
> change; a marketplace lock (campaign, flash sale) surfaces as a failed write. The received form
> carries accepted and short as two numbers; a correction is a new report and a new consent. The
> event uplift (d.1) is a multiplier on the forecast term, applied only to seller-entered event
> dates in v1, with a 90-days-of-supply upper guard on any proposed order.

1. **Two labelled numbers, summed into one agent-proposed order quantity.** The **baseline** is
   TikTok's recommended replenishment, shown as TikTok's. The **event uplift** is Juli's:
   `expected event sales − run-rate sales` for the event window, computed from the seller's own
   uplift on the same SKUs in prior events (the event outcome store, d.4) or a category default
   when the seller has none, **plus** the campaign stock the seller intends to lock, **minus**
   stock on hand and stock already on order. The card states which part is whose; the seller edits
   the total. The baseline keeps the rule that the card never shows a number the seller cannot
   find in Seller Center; the uplift is the one number TikTok does not provide. *Rejected:* a single
   Juli forecast absorbing both — when it differs from the dashboard the seller cannot tell why.

2. **One run, two attested reports; the report form is the confirmation.** The card carries the
   order quantity (d.1), the **supplier and lead time** as agent-proposed fields remembered from
   the seller's prior runs on that SKU, and a **needed-by date** computed backwards from the
   campaign stock-lock date minus lead time. Approval creates the run. The run then pauses on a
   checklist item Juli cannot perform — placing the order — and enters **`waiting_external`**.
   **First report, "ordered":** order reference, quantity ordered, expected date; no write. The
   reaper policy becomes the expected date plus a margin; the deadline clock nags before the
   needed-by date. **Second report, "received":** quantity received, **per warehouse** if the
   product is multi-warehouse. **The report form is the confirmation**: it states exactly what Juli
   will write — *"add N to available at warehouse W"* — and ADR-075's params hash binds the
   **seller-supplied** values. This is the one consent-schema change this family needs: the hash
   over seller-supplied rather than model-supplied parameters, single-use, who/when recorded, the
   card snapshot retained. **Re-verify, then the single write:** re-read available and committed
   stock, check the auto-restock setting, respect the Luôn sẵn hàng committed quantity, validate
   the warehouse allocation; then one **Update Inventory** call; then inventory webhook #27/#68
   confirms it landed. **Intervention guard:** if available stock rises through a manual edit
   during the wait, the seller restocked themselves — the run closes `seller_modified` and writes
   nothing. *Rejected:* two separate cards (order, then a scheduled receipt card) — it loses the
   chain between what was ordered and what arrived, and turns the expected-date nudge into a guess.

3. **During the event: reconcile stranded stock in batches; recommend the toggle before the event;
   never flip it unasked.** Driven by order webhook #1 and cancellation webhook #11, a
   **reconciliation run per window** tallies, per SKU with auto-restock OFF, the valid
   cancellations whose stock TikTok did not return, and proposes one batch — *"14 cancelled orders,
   23 units not back in stock, add them back"* — with one confirmation and one Update Inventory
   write, re-verified against current available and committed stock (ADR-092's batch shape applied
   to stock). **Excluded always:** seller cancellations for out-of-stock, orders already shipped
   (the return path), any SKU under a Luôn sẵn hàng lock. **Pre-event toggle card, confirm-only:**
   in the readiness window one card lists the campaign SKUs with auto-restock OFF and proposes
   turning it ON for the event through the stock-operation-settings endpoint, with a matching card
   to turn it OFF after. The card carries a field the seller answers once and Juli remembers —
   *"do you sync stock from an ERP or sell on other platforms?"* — and if yes the toggle card is
   never offered again; reconciliation is the only path. **No automatic flip, ever.** *Rejected:*
   toggle-only (wrong for exactly the sellers with the problem, and rests on an uncaptured
   endpoint); doing nothing until after the event (misses the spike).

4. **Stage A is a risk monitor with three signals, and the measure is stock health, not revenue.**
   The monitoring stage emits cards on: **stockout-by date** under the event uplift (feeds d.1's
   replenish run); **stranded committed stock** — cancelled, not returned, auto-restock OFF (feeds
   d.3's reconciliation run); and **post-event excess**, which hands off to Clear Excess
   (ADR-091). One card per signal per product; every run still pulls one lever.
   **Measures, three layers, none of them revenue:**
   - *Did-the-job facts.* Units added ÷ units proposed; received before the needed-by date, yes
     or no; for reconciliation, units restored ÷ units stranded.
   - *Risk outcome — the forecaster's report card.* Whether available stock hit zero in the event
     window and for how long; actual event sales per SKU against the proposed uplift. Both are
     written to the **event outcome store** (seller × SKU × event) and feed the uplift multiplier
     for the seller's next event — the learning loop that makes the forecast the seller's own
     after one event.
   - *Impact reading — a stock-health series.* Per replenished SKU: days of supply before and
     after, stockout hours in the window, stranded units restored. Owner decision 2026-09-05: this
     workflow measures **the ability to keep stock healthy**; it produces **no revenue reading**,
     during events or otherwise, and ADR-077's reader is not invoked for it. The card's KPI tie
     stays as ADR-055 d.15 has it; Stock Health is not one of ADR-049's five card KPIs, so the
     card slot is unchanged unless ADR-049 is amended — the same posture as ADR-091 d.6.
   *Rejected:* write-only measures (nothing improves the next forecast; nothing says whether the
   seller ran out); a revenue reading for this workflow (confounded by the campaign it serves, and
   not what the workflow is for); a counterfactual "revenue saved" (a model on a model, and a
   projected magnitude the plan-review rules forbid).

5. **Honest end states**, per ADR-090 d.7:

   | Run | Cause | Meaning |
   |---|---|---|
   | Replenish | `received_and_updated` | Goods received, stock written, webhook confirmed |
   | Replenish | `received_partial` | Fewer units than ordered; stock written with the received number, shortfall stated |
   | Replenish | `not_ordered` | No "ordered" report by the needed-by date; closed with a card revision |
   | Replenish | `not_received_by_needed_date` | Ordered, not received when the lock date arrived; stock unchanged; revision proposes what remains |
   | Replenish | `seller_modified` | Stock rose by a manual edit during the wait; nothing written |
   | Replenish | `declined` | The seller declined the order proposal |
   | Reconciliation | `reconciled` / `nothing_stranded` / `declined` / `seller_modified` | As named; `seller_modified` when the seller restored stock by hand before the batch |
   | Toggle | `toggled_on` / `toggled_off` / `declined` / `not_offered` | `not_offered` when the seller has said they sync from an ERP |

   A partial receipt is a success with a stated shortfall, never a failure. A run that wrote
   nothing produces no stock-health reading.

## End-to-end steps

**Stage A — risk monitor; Stage B — approval**

| # | Step | Mechanism |
|---|---|---|
| A1 | Read available and committed stock per SKU | Inventory Search |
| A2 | Days of supply with TikTok's formula; event uplift from the outcome store or category default; campaign lock date from the calendar | d.1, d.4 |
| A3 | Emit one card per signal per product: stockout-by, stranded stock, post-event excess (→ ADR-091) | ADR-087 standard path |
| B1 | Replenish card: baseline (TikTok's) + uplift (Juli's) = proposed order quantity; supplier and lead time remembered; needed-by date; the ERP/multi-platform field if not yet answered | d.1, d.2, d.3 |
| B2 | Approval snapshots quantity, supplier, dates | ADR-075 |

**Stage C/D — replenish run (suspended twice)**

| # | Step | Mechanism |
|---|---|---|
| C1 | Checklist item: place the order with the supplier | human, no API |
| D1 | `waiting_external` until the **"ordered"** report (reference, quantity, expected date); nag before needed-by | d.2 |
| D2 | `waiting_external` until the **"received"** report (quantity, per warehouse) — the report form is the confirmation, params hash over seller-supplied values | d.2 |
| C2 | Re-verify: available/committed re-read, auto-restock state, Luôn sẵn hàng lock, warehouse allocation | d.2 |
| C3 | **Update Inventory** — the single write | `POST /product/202309/products/{id}/inventory/update` |
| C4 | Inventory webhook confirms; completion copy states days of supply before/after | #27 / #68 |
| D3 | Intervention: manual stock rise during the wait → `seller_modified` | ADR-091 d.5 guard |

**Stage C — reconciliation run (event window)**

| # | Step | Mechanism |
|---|---|---|
| R1 | Tally valid cancellations per SKU with auto-restock OFF whose stock did not return | webhooks #1, #11; exclusions per d.3 |
| R2 | CONFIRM: the batch as the single proposal | ADR-092 shape |
| R3 | Re-verify against current available/committed; Update Inventory for the still-valid subset | d.2 guards, subset only |

**Stage E — measure.** Facts (units added ÷ proposed; on time), the risk outcome into the event
outcome store, and the stock-health series as the impact reading. No revenue.

## Consequences

- **Tool set.** `search_inventory` (READ), `get_stock_operation_settings` / `update_stock_operation_settings`
  (READ / WRITE-CONFIRM, uncaptured), `update_inventory` (WRITE-CONFIRM, §B-1 captured), plus the
  cancellation/order webhook consumers for the reconciliation tally. No supplier tool exists;
  the supplier is a checklist item and two attested reports — *amended 2026-09-08:* two supply
  events on an intake pipe whose v1 source is the seller's form. No per-supplier API at any
  version.
- **Attested report as consent.** `run_confirmations` gains a report kind whose bound parameters are
  seller-supplied; the report form renders the exact write; per-warehouse quantities when
  multi-warehouse. Shared with Process Order v2's pack-time "short" control. *Amended
  2026-09-08:* the report is stored as a **supply event** with a `source` (v1 `seller_form`),
  per-field confidence and a source-document reference; the hash binds the **confirmed**
  values, and only confirmed receipts reach the write.
- **Event outcome store.** A small table keyed seller × SKU × event holding proposed uplift, actual
  event sales, stockout hours, and stranded units restored; read by d.1, written by d.4.
- **Data items (amended 2026-09-08).** `supply_events` (one row per "ordered"/"received" report:
  `source`, parsed fields, per-field confidence, source-document reference, `confirmed_by` /
  `confirmed_at`), `purchase_orders` (draft → sent → acknowledged → partially_received →
  received → closed), `receipts` (one per delivery, accepted and short per line), and
  `suppliers` (per shop: stable id, name, lead time, contact fields, supplier-SKU → Juli-SKU
  alias map).
- **Sanitiser provenance (amended 2026-09-08).** ADR-070 d.3's source-role vocabulary gains
  `supplier`, handled untrusted like `vendor` — data, never instructions, never a fact.
- **Card fields.** `supplier`, `lead_time_days`, `needed_by`, and the once-answered
  `syncs_stock_externally` flag remembered per shop. *Amended 2026-09-08:* supplier and lead
  time resolve from the shop's `suppliers` record (a `supplier_id` reference), not from the
  card payload.
- **`execution_layer.md` §3 rewrite** as its own slice: step 2a's "Supplier/ERP API" rows become
  the checklist + two reports; add the reconciliation lever and the toggle card; the FBT branch
  stays deferred with its three preconditions.
- **Contract captures needed** on the sandbox: Update Stock Operation Settings (get and update),
  Inventory Search with a non-zero `committed_quantity`, Update Inventory on a multi-warehouse SKU.
- **Common structure instantiation.** Subject: product (SKU evidence). Trigger: risk monitor,
  three signals. Deterministic rule: baseline + uplift, needed-by date, reconciliation tally.
  Single write: Update Inventory (or the toggle, on its own card). Suspended: yes, twice. Guards:
  re-verify, auto-restock state, Luôn sẵn hàng lock, warehouse allocation, intervention guard.
  Measure: stock-health series; no revenue.
- **Risk.** Two unverified facts: whether the stock-operation-settings endpoint exists live, and
  how fast the inventory webhooks report a cancellation's stock effect. Neither touches d.1 or d.2;
  both sit inside d.3, which degrades to reconciliation-only if the endpoint never captures.
