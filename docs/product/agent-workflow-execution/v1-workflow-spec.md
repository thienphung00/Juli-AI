# Agent workflows — v1 specification

> **Owner directive, 2026-09-05.** Every workflow designed so far ships as **v1 with limited
> functionality: minimal, viable and safe.** This document is the single v1 specification —
> functional requirements (FR) and non-functional requirements (NFR) per workflow — and the
> input to `to-prd`. Design rationale lives in the ADRs; this file states *what v1 does and
> does not do*. Mega Sale Readiness is **deferred to v2** in its entirety.

| Workflow | Design | v1 status |
|---|---|---|
| Optimize Product | [ADR-090](../../adr/090-optimize-product-realignment.md) | v1 specified below |
| Clear Excess Inventory | [ADR-091](../../adr/091-clear-excess-inventory-design.md) | v1 specified below |
| Process Order | [ADR-092](../../adr/092-process-order-dispatch-design.md) | v1 specified below (already split in the ADR) |
| Replenish Inventory | [ADR-093](../../adr/093-replenish-inventory-design.md) | v1 specified below |
| Mega Sale Readiness | — | **v2**, not designed |

Where this document trims a decision an ADR records for the full workflow, the trim is listed
under **Deferred to v2** and marked **⚠ trims ADR-0xx d.n**, so the ADR stays the design of
record and v1 is an explicit, reversible subset.

---

## 1. Shared v1 requirements — every workflow

These apply to all four workflows. A workflow PRD references this section instead of restating it.

### 1.1 Functional (S-FR)

| # | Requirement |
|---|---|
| S-FR-1 | **Five-stage structure.** Monitoring → card and approval → run → (suspended close-out where the workflow waits on the world) → measure, per `PLAN.md` §14 "Common workflow structure". Identical seller-facing surfaces: card, plan review, confirmation sheet, digest, completion message, exception list. No workflow adds a surface. |
| S-FR-2 | **Approve is run creation** (ADR-075). No other path creates a run. |
| S-FR-3 | **One lever per run; single proposal.** Exactly one CONFIRM pause with one option (N = 1). The proposed change names the concrete write and its consequences. |
| S-FR-4 | **Deterministic numbers.** Every price- or quantity-bearing parameter is computed by a rule from configuration and vendor data; the model chooses subject, wording and whether to proceed, and calls the tool with exactly the computed parameters. |
| S-FR-5 | **Re-verify before the write.** The run re-reads the vendor state immediately before its write; a proposal that no longer holds is dropped or narrowed, never widened. |
| S-FR-6 | **Exactly one write per run** (single or batch). No workflow cancels an order, writes a base price, or writes stock below a committed quantity. |
| S-FR-7 | **Honest end states.** Every run ends `completed` with a named cause or on the existing failure terminal; "nothing to do" is never a failure; a run that wrote nothing produces no impact reading. |
| S-FR-8 | **Intervention closes the run** (where a run is suspended): an external change to the thing Juli created ends the run; Juli reverts nothing and re-issues no card for that thing. |
| S-FR-9 | **No repeat consent, no level-1 autonomy in v1.** Every write follows a fresh approval and a fresh confirmation, except where an ADR names the seller's own condition as the consent (Clear Excess goal, Replenish receipt report). |
| S-FR-10 | **Cards through the standard path only** (ADR-087): subject-scoped, one active card per subject per workflow, revisions only on a basis change, suppression with a named reason. |

### 1.2 Non-functional (S-NFR)

| # | Requirement |
|---|---|
| S-NFR-1 | **Safety.** Fail-closed guards at dispatch; vendor rejection after a passing validator is a surfaced failure, never a silent retry. Nothing is irreversible without a fresh human tap, and every write's reversibility is stated in the proposed change. |
| S-NFR-2 | **Consent integrity.** Params-hash binding on every confirmation (ADR-075); 4 h confirmation expiry; approvals rate-limited 5/h burst 2 per shop; subset-only execution after re-verify. |
| S-NFR-3 | **Boundary.** Production reads, sandbox writes until the production-write gate (#1339) passes; credential binding verified (ADR-068 amendment); the model never sees a client, credential or endpoint. |
| S-NFR-4 | **Sanitisation and copy.** Every vendor result passes the inbound chokepoint; every seller-facing string passes the outbound banned-pattern guard; Vietnamese, second person, no internal identifiers, no projected impact magnitudes, no causal claims. |
| S-NFR-5 | **Volume (v1 = normal operation only).** One run fits the 300 s working budget; batch writes are capped per run (Process Order: one Batch Ship; Clear Excess: ≤ 300 items per request). Mega-sale volume is v2. |
| S-NFR-6 | **Reliability.** Scheduled runs tolerate a missed cadence (the next run covers the gap); webhook-driven resumes degrade to the reaper policy if the webhook never arrives; a suspended run has its own reaper policy, never `waiting_approval`'s. |
| S-NFR-7 | **Observability.** Every tool call is a ledger row; every run emits the typed event stream; every end state is countable; did-the-job facts are unhedged and separate from impact readings. |
| S-NFR-8 | **Tenancy.** Beat tasks and monitors read tenant rows only under per-tenant context (ADR-089); no fleet-wide read without a named exemption. |
| S-NFR-9 | **Proof before ship.** Each workflow's first live proof is a sandbox walk of its single write on the deployed host, recorded on its gate issue; no workflow is called "working" on unit tests alone. |
| S-NFR-10 | **Contracts.** Every endpoint a workflow calls is captured in `contract-collection.md` before implementation; uncaptured endpoints are v2 by definition. |

---

## 2. Optimize Product — v1

**Purpose.** Make one evidence-backed change to one listing, with consent, and measure it.
**Subject.** Product. **Wave.** W9-A.

### Functional

| # | Requirement |
|---|---|
| OP-FR-1 | The run reads TikTok's product diagnosis first (Product Information Issue Diagnosis), then SEO words and suggestions. A field with no returned diagnosis code is never edited. |
| OP-FR-2 | The run proposes exactly one lever: **one listing field** (title, description or images) backed by a diagnosis code, **or one Product Discount**. |
| OP-FR-3 | Repricing happens only through `create_product_discount` (direct discount, 30-day default). No base-price write exists in the tool set. |
| OP-FR-4 | Discount depth is computed by the pricing rule from the T9 margin floor and the 1–90 % band; the model may not choose a depth. |
| OP-FR-5 | A locked SKU (campaign or flash deal) is detected by the vendor's rejection of the discount create; the run then continues with a content lever if one has evidence, else ends `completed` with cause `price_lever_locked`. |
| OP-FR-6 | Title edits enforce ≥ 25 characters; the run never edits title, category, images and description together. |
| OP-FR-7 | The proposed change states: the field or the depth, the 30-day window, the ≥ 1-day hold, and that a discount lowers the floor a future flash sale must beat. |
| OP-FR-8 | End states: `no_diagnosis_codes`, `price_lever_locked`, `scope_unavailable`, `declined`, plus the write success; vendor error on the diagnosis read after retry = failure terminal. |
| OP-FR-9 | No repeat consent. The discount lapses on its own at 30 days; **v1 does nothing on lapse** — the nightly scoring re-emits a card when the basis warrants it. |

### Non-functional

| # | Requirement |
|---|---|
| OP-NFR-1 | Preconditions: the app holds `seller.product.optimize`; both diagnosis endpoints and a `DIRECT_DISCOUNT` create are captured on the sandbox; if the scope is absent the workflow degrades to Juli's own scoring and its copy says so. |
| OP-NFR-2 | Copy never claims the Price Diagnostics tier or the card recommendations (no API); "TikTok flags…" only when a code was returned. |
| OP-NFR-3 | Impact reading on the tied KPI (CTOR) at 7 and 14 days, hedged. |

### Deferred to v2

- Lapse-driven card revision through the event spine (**⚠ trims ADR-090 d.6** — v1 is silent lapse with scoring re-carding; the standard emission path is the same in both, so no duplicate-card risk changes).
- Search Activities as a pre-proposal lock check (uncaptured); Optimize Images; N > 1 options.

---

## 3. Clear Excess Inventory — v1

**Purpose.** Move deep, slow stock with one time-boxed discount toward a seller-set goal.
**Subject.** Product (SKU evidence). **Wave.** W10.

### Functional

| # | Requirement |
|---|---|
| CE-FR-1 | Excess = TikTok's formula: days of supply (available ÷ 30-day daily forecast) above the threshold (default 90, seller-adjustable) **and** 30-day sell-through below its threshold. Exclusions: campaign-locked, creator-reserved, Luôn sẵn hàng committed, SKUs labelled Thanh lý, SKUs in a live Juli promotion. |
| CE-FR-2 | The only lever is a Product Discount (direct discount, 30-day default) via `create_product_discount`. No flash sale, no markdown, no stock write. |
| CE-FR-3 | The pricing rule computes the envelope and one recommended depth per SKU; the validator re-checks the eight rules (band, margin floor, window, price below list computed off list, collision, stock buckets, purchase limits, batch ≤ 300) plus the disclosure check; one forced re-proposal on a clampable violation. |
| CE-FR-4 | The card carries an agent-proposed **stock goal** (≈ 30 days of supply), seller-editable, `0 ≤ goal < sellable`, restated at CONFIRM. |
| CE-FR-5 | When `units_to_clear ≤ 99`, the discount's total purchase limit equals `units_to_clear` so TikTok enforces the goal. |
| CE-FR-6 | After the write the run enters `waiting_external`; on inventory webhook available ≤ goal it deactivates the activity **without a fresh confirmation** and notifies; on activity expiry it ends with the cause named. |
| CE-FR-7 | Any seller change to the activity or an upward stock move closes the run `seller_modified`; Juli changes nothing. |
| CE-FR-8 | The Thanh lý label is a human checklist item shown at approval; Juli neither sets nor verifies it and says so. |
| CE-FR-9 | End states: `goal_met`, `expired_stock_remaining`, `expired_goal_met`, `seller_modified`, `already_in_promotion`, `nothing_sellable`, `no_safe_discount`, `declined`. |

### Non-functional

| # | Requirement |
|---|---|
| CE-NFR-1 | Preconditions: `DIRECT_DISCOUNT` create, Deactivate Activity captured; `waiting_external` with its reaper policy (discount window + margin) and the intervention guard landed as shared code. |
| CE-NFR-2 | Collision check is declared unchecked until Search Activities captures; the vendor is the lock signal. |
| CE-NFR-3 | Measure: goal progress (`units cleared ÷ units to clear`) as the fact; days of supply before/after recorded on the run; card KPI unchanged (AOV). |
| CE-NFR-4 | Copy: the irreversibility statement is removed (ADR-091 d.8); the proposed change states the window, the hold and the flash-sale floor effect. |

### Deferred to v2

- Card revision on expiry proposing republish (**⚠ trims ADR-091 d.4 second branch** — v1 ends `expired_stock_remaining` and lets scoring re-card); `republish_activity`; Search Activities; Flash Sale as a gated lever; revenue impact reading on the cleared SKUs (v1 records the facts only).

---

## 4. Process Order — v1

**Purpose.** Arrange shipment for every clean order before its deadline, with one tap per window.
**Subject.** Dispatch window (Order for v2 exceptions). **Wave.** W10. The ADR already carries
the v1/v2 split; restated here for completeness.

### Functional

| # | Requirement |
|---|---|
| PO-FR-1 | Scope: fulfilled by seller with platform shipping only. FBT and own-carrier orders are listed in the digest, never acted on. |
| PO-FR-2 | Two scheduled runs a day. Each run reads orders awaiting shipment whose `rts_sla` falls before the next run, sorted by deadline. |
| PO-FR-3 | Clean predicate: awaiting shipment, past the 1 h hold, fulfilled by seller, no cancellation request pending or opened since read, no address update since read, stock > 0 on the system bucket, no ship error or abnormal state. |
| PO-FR-4 | One batch confirmation: the sheet shows count, earliest deadline, orders by bucket, and excluded orders with reasons. One tap. |
| PO-FR-5 | Before the write every order and its packages are re-read; the run executes a **subset** of the confirmed batch, never a superset; dropped orders are named with reasons. |
| PO-FR-6 | Exactly one write: Batch Ship Packages for the still-clean subset, read **per package**; partial success is reported as partial. Labels, pick list and packing slip are fetched after. |
| PO-FR-7 | Exceptions are notification-only: every excluded or dropped order in the digest with its reason and a deep link. Nothing is cancelled. |
| PO-FR-8 | One push 2 h before the earliest deadline if unconfirmed; on expiry the next run re-proposes with urgency. Never auto-ship. |
| PO-FR-9 | End states: `shipped_all`, `shipped_subset`, `nothing_clean`, `confirmation_expired`, `declined`, `vendor_partial_failure`. |

### Non-functional

| # | Requirement |
|---|---|
| PO-NFR-1 | Preconditions: `fulfillment_type`, `shipping_type`, `delivery_option_id` values captured; Batch Ship and its partial-error shape captured on the sandbox; live `package_status` enum recorded. |
| PO-NFR-2 | Volume: normal operation; a batch above the per-run cap waits for the next run (no chunking in v1). |
| PO-NFR-3 | The cancellation and address guards are structural (predicate + re-verify), not prompt rules. |
| PO-NFR-4 | Measure: orders shipped before `rts_sla` ÷ orders due, per run. Card KPI unchanged (Cancellation rate). |

### Deferred to v2 (the mega-sale NFR)

Chunking, three runs and higher cadence, 6 h + 2 h nag and last-chance card, per-order exception cards with the re-arrange write, pack-time "short" control, combine/split proposals, own-carrier orders with tracking input and Update Package Delivery Status, and the standing approval (level 1).

---

## 5. Replenish Inventory — v1

**Purpose.** See a stockout coming, get the order placed in time, and write the received stock
safely. **Subject.** Product (SKU evidence). **Wave.** W10.

### Functional

| # | Requirement |
|---|---|
| RI-FR-1 | Monitoring signal in v1: **stockout-by date** — days of supply (TikTok's formula) against lead time, with the event uplift applied when a campaign date is known for the shop. |
| RI-FR-2 | The card proposes **two labelled numbers**: TikTok's recommended replenishment (baseline, shown as TikTok's) plus Juli's event uplift (from the seller's prior-event record if any, else a category default), summed into one agent-proposed order quantity the seller edits. |
| RI-FR-3 | The card carries supplier and lead time as agent-proposed fields remembered from prior runs, and a needed-by date. |
| RI-FR-4 | One run, suspended twice in `waiting_external`: a checklist item to place the order; the **"ordered"** report (reference, quantity, expected date); the **"received"** report (quantity, per warehouse if multi-warehouse). **The received-report form is the confirmation**: it states the exact write and the params hash binds the seller-supplied values. |
| RI-FR-5 | Before the write: re-read available and committed stock; check the auto-restock setting; respect the Luôn sẵn hàng committed quantity; validate warehouse allocation. Then exactly one write: Update Inventory. |
| RI-FR-6 | A manual stock rise during the wait closes the run `seller_modified`; nothing is written. |
| RI-FR-7 | Deadline: the reaper policy is the expected date plus a margin; the clock nags before the needed-by date. |
| RI-FR-8 | End states: `received_and_updated`, `received_partial`, `not_ordered`, `not_received_by_needed_date`, `seller_modified`, `declined`. A partial receipt is a success with a stated shortfall. |

### Non-functional

| # | Requirement |
|---|---|
| RI-NFR-1 | Preconditions: Inventory Search with a non-zero `committed_quantity` and Update Inventory on a multi-warehouse SKU captured; the attested-report consent kind (seller-supplied params) landed as shared code with `waiting_external`. |
| RI-NFR-2 | Measure = **stock health, no revenue**: units added ÷ proposed; received before needed-by; days of supply before/after; whether available stock hit zero before receipt. Forecast vs actual is recorded on the run for the next event's uplift. |
| RI-NFR-3 | Stock locks at order placement (`committed_quantity`), never at add-to-cart; the write never reduces available below committed. |
| RI-NFR-4 | No supplier integration exists; the supplier is two reports and a checklist item. |

### Deferred to v2

- The **stranded-stock reconciliation run** and the **auto-restock toggle card** (**⚠ trims ADR-093 d.3** — both are event-time levers on an uncaptured endpoint); the post-event-excess signal (Clear Excess re-cards on its own); the separate event outcome store (v1 records forecast vs actual on the run itself); FBT.

---

## 6. Shared code that v1 needs before any of the four ships

From `PLAN.md` §14 design-order item 0, restricted to what v1 uses:

1. `workflow_key` on runs; polymorphic bound subject (product, dispatch window); domain-registered tool dispatcher; shared prompt sections; de-pinned gate tests; step input contracts.
2. `waiting_external` run state with a per-workflow reaper policy and the **intervention guard** (Clear Excess, Replenish).
3. The **attested-report** confirmation kind — params hash over seller-supplied values (Replenish).
4. Scheduled card producers per window (Process Order) and per risk signal (Replenish).
5. **Not in v1:** the deadline clock as a shared escalation service (each v1 workflow uses one push at a fixed offset), the autonomy ladder, the event spine additions (#13/#14), the event outcome store.

## 7. What "viable" means for v1

A seller can, on the deployed host against the sandbox shop: approve one Optimize Product card and see one discount or one field change land; approve one Clear Excess card, set a goal, and see the discount end when the goal is met; approve one dispatch batch and print its labels; approve one replenish order, report it received, and see stock updated. Each of those four is one gate walk, recorded on its issue, before the workflow is called working.
