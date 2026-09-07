# ADR-092: Process Order — a per-window dispatch batch, one confirmation, and a region-correct chain

**Status:** Proposed
**Date:** 2026-09-04
**Deciders:** grill-with-docs (Architect) with user

**Amends:** [`execution_layer.md`](../product/execution_layer.md) §5A, §5B and §6 — the chain
encodes the US "purchase shipping" flow and Vietnam is on "schedule shipping";
[ADR-087](087-subject-scoped-action-cards-and-card-revisions.md) d.5 — Process Order gains a
second subject, the **dispatch window**, beside Order for exceptions.
**Builds on:** [ADR-090](090-optimize-product-realignment.md) (honest end states, one lever per
run), [ADR-091](091-clear-excess-inventory-design.md) (re-verify before the write, `waiting_external`
and the intervention guard for the v2 exception paths), [ADR-075](075-agent-approval-gate-and-security-prerequisites.md)
(approval gate, rate limits, decision request), [ADR-088](088-consent-pause-is-a-runner-guarantee.md).
**Scope:** W10, [`PLAN.md` §14](../product/agent-workflow-execution/PLAN.md) design-order item 3.
An everyday operations workflow; sustained high volume during a mega sale is its **non-functional
requirement**, delivered as v2 on the same shape.

## Context

**Region, not fulfilment model, decides the API shape.** Vietnam is SEA, and SEA uses the
Partner API's *schedule shipping* flow, not the *purchase shipping* flow the US and Japan use
([`seller-journeys/process-order-actors.md`](../product/agent-workflow-execution/seller-journeys/process-order-actors.md)
§B). `execution_layer.md` §5A was written against the US chain and carries four defects:

1. **Create Packages is US/JP-only.** In Vietnam TikTok creates the package at order time —
   production orders already carry `packages[]` before any seller action. Step 4 must become a
   read that yields `package_id`.
2. **Confirm Package Shipment is not a seller endpoint** — certified warehouse providers only.
   Step 7 is deleted.
3. **Steps 5a and 6a are inverted.** The shipping document exists only *after* Ship Package.
4. **Step 5b is wrong for SEA.** Ship-by-seller does not skip a TikTok call; it *is* Ship Package
   with `self_shipment`. Mark Package As Shipped is US/EMEA/JP-only.

**Ship Package is the pivotal write.** It schedules the handover slot and method, assigns the
carrier, generates the label, and moves the order to `AWAITING_COLLECTION`; after it the buyer can
no longer cancel without seller approval. The courier scan — not a seller call — drives
`IN_TRANSIT` and everything after. Three facts bite at volume: shipping and package writes are
**documented as forbidden while a cancellation request is pending**, and the execution layer has
no such guard; **Batch Ship Packages returns a top-level success with per-package
`data.errors[]`**, so a caller that checks only the top-level code reports phantom successes; and
the order record itself carries the three deadlines — `rts_sla`, `tts_sla`, `cancel_order_sla` —
so no cutoff needs recomputing.

**Fulfilled by TikTok is monitor-only by design.** The ship endpoints refuse FBT orders
(`21008025 "Seller cannot operate orders which are fulfilled by platform"`), and the Vietnamese
seller corpus does not corroborate FBT at all. **Seller Own Fleet** adds one mandatory write —
Update Package Delivery Status, allowed only ≥ 24 h after shipping, with tracking editable for
36 h, TikTok cancelling on day 13 from payment, two delivery attempts before failure, and no COD.

**Consent machinery constrains the grain.** Approvals are rate-limited to 5 per hour per shop
(ADR-075 d.4); a confirmation expires in 4 h; a run has a 300 s working budget (ADR-073); level-1
pre-approval does not exist server-side; and Seller Center already batch-arranges shipment in a
few clicks, so the seller's bottleneck is **packing**, not clicking. Juli's value is timing
(packages arranged before the packer arrives), the guards Seller Center does not apply, and a
deadline-ordered pick list.

**Contract gaps.** `shipping_type`, `delivery_option_id` and `FULFILLMENT_BY_TIKTOK` — the exact
fields the workflow branches on — appear in **zero** live captures in
[`contract-collection.md`](../integrations/tiktok_api/contract-collection.md), and the live sandbox
`package_status` values `TO_FULFILL` / `STOCKING` are outside the documented enum.

## Decisions

1. **Grain: one run per dispatch window per shop, one batch confirmation.** The card's subject is
   the **dispatch window** (a Juli entity: shop + the deadline bucket the run covers), amending
   ADR-087 d.5; exceptions keep **Order** as their subject. The run reads the awaiting-shipment
   list, applies the clean predicate (d.2), and pauses at the existing CONFIRM with the whole
   clean batch as the **single** proposal — *"N orders due by 23:59, ship all"* — then performs
   one Batch Ship. This uses only machinery that runs today: one card, one approval, one
   confirmation, one write, one terminal state, and a human look at every batch. *Rejected:*
   per-order runs (the 5/h approval limit makes them unusable past five orders an hour); a
   continuous event-driven run (non-terminal, breaks the reaper and the impact reader, needs
   level-1); monitoring-only (no attributable impact, the seller still clicks in two screens).

   > **Option 2 — planned and deferred.** A standing per-shop approval, *"Juli may arrange
   > shipment for clean orders"*, executing Ship Package at level 1 with a digest and no per-batch
   > confirmation. It waits for the autonomy ladder (`PLAN.md` §14 NFR mechanism 3). When it lands
   > it is a **playbook policy flip** on this same run — confirm-the-batch becomes
   > pre-approved-with-digest — not a redesign; event-driven micro-batches become its natural
   > cadence. Until then, nothing in this workflow ships without a tap.

2. **The clean predicate, and two race guards.** An order is *clean* when every condition holds:
   status `AWAITING_SHIPMENT`, past the one-hour `ON_HOLD` remorse window; fulfilled by seller;
   **no cancellation request pending or opened since the order was read**; **no recipient address
   update since the packages were read**; every line has available stock > 0 on the system bucket
   (physical shortfall is a pack-time exception, not a predicate failure); no ship error and no
   abnormal-package state; *(v2)* combine resolved and shown as its own sub-list in the proposal;
   *(v2)* own-carrier orders only with a seller-supplied tracking number. The predicate is
   evaluated twice: at proposal, and **immediately before each order's Ship call** — the
   confirmation can sit for 4 h, and TikTok may have split the order itself after an address
   change, so the order *and its packages* are re-read. **The run may execute a subset of the
   confirmed batch, never a superset**: the params hash still binds the confirmed list, the write
   covers only orders still on it and still clean, and every dropped order is named in the digest
   with its reason. Batch Ship is read **per package** — a top-level success with per-package
   errors is a partial success, surfaced as such; errors that advise cancellation never cancel
   anything. A cancellation request that arrives *after* shipping belongs to the cancellation
   workflow (8a); Process Order surfaces it and does not decide it. *Rejected:* shipping the
   confirmed list literally — it ships over a documented prohibition and hands the seller a parcel
   to pull back from the courier pile.

3. **The deadline clock reads the order's SLA fields; it never recomputes a cutoff.** Windows are
   **deadline buckets**: a run proposes every clean order whose `rts_sla` falls before the next
   scheduled run, grouped "due today" / "due tomorrow" and ordered by deadline. Reading the
   timestamps sidesteps the unresolved 14:00-vs-18:00 cutoff conflict and survives OHC and campaign
   extensions, holidays and pre-orders. **v1:** two scheduled runs a day; the sheet shows count,
   earliest deadline, orders by bucket, and the excluded orders with reasons; one push **2 h**
   before the earliest deadline if the batch is unconfirmed; on expiry the next run re-proposes
   with urgency marked. **v2:** three runs a day, configurable per shop; **chunking** into bounded
   runs ordered earliest-deadline-first, each with its own confirmation (that is the mega-sale NFR
   made concrete — the same workflow, more runs); nag at 6 h and 2 h, then email; a
   **last-chance card** on expiry carrying only the orders that die before the next run.
   **Auto-shipping on expiry is never done** — that is option 2. *Rejected:* fixed clock windows
   keyed to 14:00 (encodes a contested number, misfiles extended orders); one daily batch (misses
   same-day orders that land after it; a thousand-order confirmation is a rubber stamp);
   micro-batches under batch confirmation (dozens of taps on a peak day).

4. **Exceptions: notification-only in v1, per-order cards in v2, and the cancellation writes
   belong to 8a.** **v1:** every excluded or dropped order is listed in the completion digest with
   its reason and a deep link to Seller Center; no exception cards, no exception writes. **v2:**
   per-order cards (subject Order), each of which **must confirm**:

   | Exception | The card proposes | Write |
   |---|---|---|
   | Cancellation request after shipment was arranged | Hold the parcel from handover; the 48 h decision deadline is shown. Approve/reject belong to 8a and attach to this same card when 8a lands | none here |
   | Out of stock at pack time (packer-reported) | Two paths with their cost stated: seller-fault cancel (cancellation rate, violation points) or delay with the buyer's consent | none |
   | Address update after packing, before pickup | Re-read; show whether TikTok split the order; propose re-arranging shipment for a fresh label | Ship Package on the new package |
   | Ship error advising cancellation | Show the vendor's reason and both paths; never cancel from an error string | none |
   | Failed delivery / return to seller | Checklist for the return branch and the appeal, with the 7-day reclaim window | none — no API |
   | Own-carrier delivery outcome | The seller reports delivered or failed with reason and proof; Juli uploads once the 24 h floor has passed | Update Package Delivery Status |

   Notification-only inside the digest, in both versions where they occur: combined packages,
   forced splits (e.g. phones ship alone), dropped orders, abnormal packages (> 7 days without a
   scan, with a support-ticket checklist). The pack checklist carries a per-line **"short"**
   control that raises the out-of-stock card — the same attested-fact input Replenish needs for
   "goods arrived". **Nothing is ever cancelled by Juli.** *Rejected:* Process Order owning the
   cancellation approve/reject writes (one write under two workflows, and 8a inherits half-built
   behaviour); folding exceptions into the next batch sheet (bundles judgment into a safe batch,
   which the one-lever rule forbids).

5. **Scope by fulfilment path.** **v1:** fulfilled by seller with platform shipping only; FBT and
   own-carrier orders are listed in the digest, never acted on. FBT stays **monitor-only** by
   design (`21008025`). **v2:** own-carrier orders enter the batch once a tracking number is
   supplied, Ship Package carries `self_shipment`, and Update Package Delivery Status follows the
   24 h floor, the 36 h edit window and the day-13 cancel. *Rejected:* FBT branches — no Vietnamese
   corroboration, no captures, and the vendor refuses the write.

6. **Writes and measure.** **v1** performs exactly one write: Batch Ship Packages for the
   confirmed set. **v2** adds Ship Package re-arrange (d.4) and Update Package Delivery Status
   (d.5). The did-the-job fact is `orders shipped before rts_sla ÷ orders due` per run — a fact,
   unhedged; v2 tracks late-dispatch rate over time. The card's KPI tie stays **Cancellation rate**
   (ADR-055 d.15). *Rejected:* any cancel write — every cancellation is a human act on the
   cancellation workflow's surface.

7. **Honest end states**, per ADR-090 d.7:

   | Cause | Meaning |
   |---|---|
   | `shipped_all` | Every confirmed order shipped |
   | `shipped_subset` | Some confirmed orders were dropped at re-verify; each named with its reason |
   | `nothing_clean` | No order passed the predicate; the digest lists why |
   | `confirmation_expired` | The 4 h window lapsed; the next run re-proposes |
   | `declined` | The seller declined the batch |
   | `vendor_partial_failure` | Batch Ship succeeded for some packages; per-package errors surfaced |

   A Batch Ship call that fails outright stays on the existing terminal failure path.

## v1 / v2 split

| Element | v1 — minimal, functional | v2 — mega-sale volume (the NFR) |
|---|---|---|
| Scope | FBS + platform shipping only; FBT and SOF listed, never acted on | SOF with tracking input and delivery-status upload |
| Grain | One run per scheduled cadence, two a day, one batch confirmation | Three runs, chunking, then option 2 |
| Clean predicate | Status, hold elapsed, no pending cancellation, no address update, stock > 0 | Combine/split proposals shown in the sheet (v1 ships each order as its own package — the same outcome as skipping the combine prompt, at the cost of separate parcels) |
| Guards | Re-verify before write, subset allowed, partial success read per package | unchanged |
| Deadline | SLA fields, sort by deadline, deadlines on the sheet, one push at 2 h | 6 h + 2 h nag, last-chance card, higher cadence |
| Exceptions | Notification-only with deep links | Exception cards with the re-arrange write; pack-time "short" control |
| Writes | Batch Ship only | + Ship Package re-arrange, + Update Package Delivery Status |
| Measure | Shipped-before-deadline ÷ due, per run | Late-dispatch rate over time |

## End-to-end steps (v1)

| # | Step | Who | Mechanism |
|---|---|---|---|
| A1 | Order paid → `ON_HOLD` → `AWAITING_SHIPMENT` after 1 h; package created | TikTok | webhook #1; `order.packages[]` |
| A2 | Scheduled run reads awaiting-shipment orders and their SLA fields | API read | Get Order List / Detail, Get Package Detail |
| A3 | Emit or suppress the dispatch-window card | Juli | ADR-087 standard path; suppressed when nothing is due before the next run |
| B1 | Card: count, earliest deadline, orders by bucket, excluded orders with reasons | Seller | decision plan review |
| B2 | Approval creates the run bound to the window | Seller | ADR-075 approval gate |
| C1 | Apply the clean predicate; build the batch | Juli | d.2 |
| C2 | CONFIRM pause with the batch as the single proposal, params-hash bound | Seller | ADR-075 d.2, ADR-088 |
| C3 | Re-verify each order and its packages | API read | d.2 |
| C4 | **Batch Ship Packages** for the still-clean subset | API write | `POST /fulfillment/202309/packages/batch_ship`, handover method from the shop default |
| C5 | Fetch shipping label, pick list and packing slip | API read | Get Package Shipping Document — only after C4 |
| C6 | Digest: shipped, dropped with reasons, excluded with reasons, deep links | Juli | d.4 |
| C7 | Print, pack, hand over | Seller, physical | timed checklist ordered by deadline |
| C8 | Courier scan → `IN_TRANSIT` → delivered | TikTok | polled; no package-status webhook exists |
| D | *(nothing suspended in v1)* | — | — |
| E1 | Shipped-before-deadline ÷ due | Juli | fact per run |

## Consequences

- **Tool set (v1).** `list_orders_awaiting_shipment`, `get_order_detail`, `get_package_detail`
  (READ); `batch_ship_packages` (WRITE, CONFIRM); `get_shipping_documents` (READ). **v2** adds
  `ship_package` (re-arrange, and SOF with `self_shipment`), `update_delivery_status`,
  `search_combinable_packages`, `combine_packages`. No cancel tool exists in this allowlist, ever.
- **Dispatch window as a subject.** ADR-087 d.5 amendment; a scheduled card producer per window;
  the active-run index keyed on the window so two runs never cover the same bucket.
- **`execution_layer.md` §5A/§5B/§6 rewrite** as its own slice: step 4 → read `package_id`;
  step 7 deleted; 5a/6a reordered (ship, then document); 5b → Ship Package with `self_shipment`
  after a Get Shipping Providers read; add the **cancellation guard** (webhook #11 blocks every ship
  write), the SOF **Update Package Delivery Status** step, the **failed-delivery** terminal branch,
  and the three SLA fields; §6 combine/split moved ahead of the ship write.
- **Contract captures needed** on the sandbox before implementation: `fulfillment_type`,
  `shipping_type` and `delivery_option_id` values; a Ship Package / Batch Ship call and its
  partial-error shape; the live `package_status` enum; Get Package Handover Time Slots.
- **Mega-sale NFR = the v2 column.** Nothing in v2 changes the v1 shape; each item is additive.
- **Common structure.** This ADR instantiates the five-stage structure recorded in `PLAN.md` §14
  (subject: dispatch window; trigger: scheduled read; deterministic rule: the clean predicate and
  deadline sort; single write: Batch Ship; suspended: no in v1; guards: re-verify, subset, per-package
  read; measure: shipped-before-deadline). The seller-facing surfaces are the same card, plan
  review, confirmation sheet, digest and completion message every other workflow uses.
- **Risk.** Two unverified facts decide v1's first live proof: whether Batch Ship accepts the
  shop's default handover method without a slot, and how the sandbox represents a pending
  cancellation on the order record. Both sit inside decision 2's re-verify step, which fails closed.
