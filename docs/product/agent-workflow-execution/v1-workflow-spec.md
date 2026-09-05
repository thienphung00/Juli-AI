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
| S-FR-1 | **Five-stage structure.** Monitoring → card and approval → run → (suspended close-out where the workflow waits on the world) → measure, per `PLAN.md` §14 "Common workflow structure". Identical seller-facing surfaces: card, plan review, confirmation sheet, digest, completion message, exception list, **and one deadline view** (owner waiver 2026-09-05: a single deadline/timeline surface shared by every workflow that carries a deadline — dispatch windows, needed-by dates, confirmation expiries). No workflow adds a surface beyond these seven. |
| S-FR-2 | **Approve is run creation** (ADR-075). No other path creates a run. |
| S-FR-3 | **One lever per run; single proposal.** Exactly one CONFIRM pause with one option (N = 1). The proposed change names the concrete write and its consequences. |
| S-FR-4 | **Deterministic numbers.** Every price- or quantity-bearing parameter is computed by a rule from configuration and vendor data; the model chooses subject, wording and whether to proceed, and calls the tool with exactly the computed parameters. |
| S-FR-5 | **Re-verify before the write.** The run re-reads the vendor state immediately before its write; a proposal that no longer holds is dropped or narrowed, never widened. |
| S-FR-6 | **Exactly one write per run** (single or batch). No workflow cancels an order, writes a base price, or writes stock below a committed quantity. |
| S-FR-7 | **Honest end states.** Every run ends `completed` with a named cause or on the existing failure terminal; "nothing to do" is never a failure; a run that wrote nothing produces no impact reading. |
| S-FR-8 | **Intervention closes the run** (where a run is suspended): an external change to the thing Juli created ends the run; Juli reverts nothing and re-issues no card for that thing. |
| S-FR-9 | **No repeat consent, no level-1 autonomy in v1.** Every write follows a fresh approval and a fresh confirmation, except where an ADR names the seller's own condition as the consent (Clear Excess goal, Replenish receipt report). |
| S-FR-11 | **One active run per subject, across all workflows; no duplicate write.** A product, SKU set, or order that has an active run under any workflow cannot receive a second run under another workflow until the first ends (owner directive 2026-09-05). This **narrows ADR-083/ADR-087 d.2**, which permitted two agents on one product under different categories. Workflows whose single writes share an endpoint family (Optimize Product and Clear Excess both create promotion activities; Clear Excess and Replenish both touch stock) are additionally serialised by a **write-lock registry keyed on (subject, endpoint family)** checked at dispatch, so an overlapping endpoint can never be written twice for one subject in one window. |
| S-FR-12 | **Checklist items are tracked and seller-editable.** Every human checklist item (place the order, apply the clearance label, print and pack) is a recorded item on the run: the seller ticks it, can edit its text and its done state, and the tick time is in the ledger. Ticks do not gate a run stage in v1. |
| S-FR-13 | **One decision list per workflow.** The seller sees a separate list for each workflow, never one merged list; ordering within a list is by deadline where the workflow has one, else by basis recency. |
| S-FR-10 | **Cards through the standard path only.** ADR-087's subject-scoped cards (one active card per subject per workflow, chained revisions, suppression with a named reason) are a **P0 precondition, not a landed mechanism** — today's constraint is one card per shop per workflow and the run's subject is derived at approval from the shop's highest-revenue product (§8.1). Until P0-2 lands, no v1 workflow can name "this SKU" or "this window". |

### 1.2 Non-functional (S-NFR)

| # | Requirement |
|---|---|
| S-NFR-1 | **Safety.** Fail-closed guards at dispatch; vendor rejection after a passing validator is a surfaced failure, never a silent retry. Nothing is irreversible without a fresh human tap, and every write's reversibility is stated in the proposed change. |
| S-NFR-2 | **Consent integrity.** Params-hash binding on every confirmation (ADR-075); 4 h confirmation expiry; approvals rate-limited 5/h burst 2 per shop; subset-only execution after re-verify. |
| S-NFR-3 | **Boundary.** Production reads, sandbox writes until the production-write gate (#1339) passes; credential binding verified (ADR-068 amendment); the model never sees a client, credential or endpoint. **Because v1 is done only when the whole workflow works end-to-end for a real connected seller (S-NFR-11), the production-write unlock and its RLS blocker are on v1's critical path, not after it.** |
| S-NFR-4 | **Sanitisation and copy.** Every vendor result passes the inbound chokepoint; every seller-facing string passes the outbound banned-pattern guard; Vietnamese, second person, no internal identifiers, no projected impact magnitudes, no causal claims. |
| S-NFR-5 | **Volume (v1 = normal operation only).** One run fits the 300 s working budget; batch writes are capped per run (Process Order: one Batch Ship; Clear Excess: ≤ 300 items per request). Mega-sale volume is v2. |
| S-NFR-6 | **Reliability.** Scheduled runs tolerate a missed cadence (the next run covers the gap); webhook-driven resumes degrade to the reaper policy if the webhook never arrives; a suspended run has its own reaper policy, never `waiting_approval`'s — today the reaper holds one global policy (Optimize Product's); per-run resolution is P0-4. |
| S-NFR-7 | **Observability.** Every tool call is a ledger row; every run emits the typed event stream; every end state is countable; did-the-job facts are unhedged and separate from impact readings. |
| S-NFR-8 | **Tenancy.** Beat tasks and monitors read tenant rows only under per-tenant context (ADR-089); no fleet-wide read without a named exemption. |
| S-NFR-9 | **Proof before ship.** Each workflow's first live proof is a sandbox walk of its single write on the deployed host, recorded on its gate issue; no workflow is called "working" on unit tests alone. |
| S-NFR-10 | **Contracts.** Every endpoint a workflow calls is captured in `contract-collection.md` before implementation; uncaptured endpoints are v2 by definition. |
| S-NFR-11 | **Definition of done (owner, 2026-09-05).** v1 of a workflow is done when it works end-to-end for a **real seller who has connected their own shop** at `demo.app-juli.com`: the seller's production reads, the seller's production write under their own credential and tenant isolation, and a real impact or stock-health reading. The sandbox gate walk (§7) is the *first* proof, not the last. Sellers who do not connect use the non-login demo, which serves **replayed** golden runs through the same surfaces (ADR-084). |
| S-NFR-12 | **Surface and identity.** The seller surface is the mobile-web demo app only; iOS is out of v1. Login is Google → Supabase Auth → a separate TikTok OAuth for the shop; a real merchant's runs execute under their own `seller_connect` credential. Seller copy is Vietnamese only. |
| S-NFR-13 | **Sandbox mirror.** Gate-walk data is produced by reading the connected merchant's shop and copying it into the sandbox shop (products, stock, and orders where the sandbox permits order creation — a capture item), extending the existing sandbox catalog sync. No hand-authored sandbox data. |

---

## 2. Optimize Product — v1

**Purpose.** Make one evidence-backed change to one listing, with consent, and measure it.
**Subject.** Product. **Wave.** W9-A.

### Functional

| # | Requirement |
|---|---|
| OP-FR-1 | The run reads TikTok's product diagnosis first (Product Information Issue Diagnosis), then SEO words and suggestions. A field with no returned diagnosis code is never edited. |
| OP-FR-2 | The run proposes exactly one lever: **one listing field** (title, description or images) backed by a diagnosis code, **or one Product Discount**. |
| OP-FR-3 | Repricing happens only through `create_product_discount` (direct discount, 30-day default). The registered base-price tool `update_product_price` is **deregistered** in this slice, together with its entry in `required_steps`, the field-lock map and the impact reader's measurable-tool derivation. |
| OP-FR-4 | Discount depth is computed by the pricing rule and the model may not choose it. **v1 floor (⚠ owner to confirm, §8.3):** no per-SKU cost exists and the fee-adjusted floor is structurally zero in production, so the v1 floor is a **seller-set maximum discount per shop** (agent-proposed default, editable on the card) inside the 1–90 % band; the true margin floor arrives when per-SKU cost or the ADR-065 fee mapping exists. |
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
| OP-NFR-3 | Impact reading at 7 and 14 days, hedged, on the impact reader's existing metric for the mutation kind (today: `gmv` for a price mutation, `conversion_rate` for a listing edit). **CTOR is not a metric anywhere in the codebase**; a CTOR reading is v2 if wanted. A discount write needs a new mutation kind in the reader's classifier (§8.2). |

### Deferred to v2

- Lapse-driven card revision through the event spine (**⚠ trims ADR-090 d.6** — v1 is silent lapse with scoring re-carding; the standard emission path is the same in both, so no duplicate-card risk changes).
- A pre-proposal lock check: **Search Activities does not exist at TikTok** (contract-collection A-25; a partner-corpus page describes it but the testing tool never exposed it) — collision detection is Juli-side permanently (Juli persists the activity ids it creates; the vendor rejection covers the rest). Optimize Images; N > 1 options.

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
| CE-FR-6 | After the write the run enters `waiting_external`; on inventory webhook available ≤ goal it deactivates the activity **without a fresh confirmation** and records an in-app notification; on activity expiry it ends with the cause named. Both resumes need the webhook→resume dispatcher (P0-5): webhooks are persisted to `workflow_webhook_signals` today and nothing reads that table. |
| CE-FR-7 | Any seller change to the activity or an upward stock move closes the run `seller_modified`; Juli changes nothing. |
| CE-FR-8 | The Thanh lý label is a human checklist item shown at approval; Juli neither sets nor verifies it and says so. |
| CE-FR-9 | End states: `goal_met`, `expired_stock_remaining`, `expired_goal_met`, `seller_modified`, `already_in_promotion`, `nothing_sellable`, `no_safe_discount`, `declined`. |

### Non-functional

| # | Requirement |
|---|---|
| CE-NFR-1 | Preconditions: `DIRECT_DISCOUNT` create and Deactivate Activity **captured on the sandbox** (only `FLASHSALE` and a `FIXED_PRICE` read exist today); `waiting_external` with its reaper policy (discount window + margin), the webhook→resume dispatcher and the intervention guard **landed as P0 shared code** (none exists today, §8.1); `inventory_items` populated for the reference shop (the poll cycle that writes it is not scheduled, §8.2). |
| CE-NFR-2 | Collision check is Juli-side: activity ids Juli created are persisted at create time and reconciled via webhook #39; for everything else the vendor rejection is the lock signal. There is no vendor list endpoint. |
| CE-NFR-3 | Measure: goal progress (`units cleared ÷ units to clear`) as the fact; days of supply before/after recorded on the run as a run fact (a new fact-row shape, since `impact_readings` holds DiD readings only). Card KPI **unchanged from whatever the surface renders today** — the two layers already disagree (ADR-055 d.15 says AOV; the backend catalog ties `clear_excess_4` to `inventory_turnover`/`dsi`); v1 touches neither. |
| CE-NFR-4 | Copy: the irreversibility statement is removed (ADR-091 d.8); the proposed change states the window, the hold and the flash-sale floor effect. |

### Deferred to v2

- Card revision on expiry proposing republish (**⚠ trims ADR-091 d.4 second branch** — v1 ends `expired_stock_remaining` and lets scoring re-card); `republish_activity`; Flash Sale as a gated lever; revenue impact reading on the cleared SKUs (v1 records the facts only).

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
| PO-FR-6 | Exactly one write: Batch Ship Packages for the still-clean subset, read **per package**; partial success is reported as partial. Labels, pick list and packing slip are fetched after through **new** client methods (Get Package Detail and Get Package Shipping Document exist only as guard regexes today). The `FulfillmentResource.batch_ship_packages` client exists, guarded, with zero call sites. |
| PO-FR-7 | Exceptions are notification-only: every excluded or dropped order in the digest with its reason and a deep link. Nothing is cancelled. |
| PO-FR-8 | One reminder 2 h before the earliest deadline if unconfirmed, **in-app in v1** (no push, email or Zalo transport is wired; channel is owner question §8.3); on expiry the next run re-proposes with urgency. Never auto-ship. |
| PO-FR-9 | End states: `shipped_all`, `shipped_subset`, `nothing_clean`, `confirmation_expired`, `declined`, `vendor_partial_failure`. |

### Non-functional

| # | Requirement |
|---|---|
| PO-NFR-1 | Preconditions (**none met today**): a sandbox order read path (the sandbox allowlist has no order path and `OrdersResource` is production-only, so the run cannot re-read what it ships); at least one awaiting-shipment order captured **with `rts_sla`/`tts_sla`/`cancel_order_sla`, `fulfillment_type`, `shipping_type`, `delivery_option_id`** (both existing captures are of a cancelled order and carry none of them); a real Batch Ship walk with its partial-error shape (the current contract row is a hand-written example); the live `package_status` enum. **If the SLA fields turn out absent from the order record, PO-FR-2's sort key falls back to the documented cutoff rule and that fallback is an owner decision (§8.3).** |
| PO-NFR-2 | Volume: normal operation; a batch above the per-run cap waits for the next run (no chunking in v1). |
| PO-NFR-3 | The cancellation and address guards are structural (predicate + re-verify), not prompt rules. |
| PO-NFR-4 | Measure: orders shipped before `rts_sla` ÷ orders due, per run (today's proxy is a global 48 h constant from payment time; replaced by the observed field). Card KPI unchanged. |

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
| RI-FR-2 | The card proposes **two labelled numbers**: the **baseline, computed by Juli with TikTok's dashboard formula** (`forecast × period − available`) and labelled *"tính theo công thức của TikTok"* — **no Partner endpoint returns TikTok's recommendation**, so it is never labelled as TikTok's number — plus Juli's event uplift (from the seller's prior-event record if any, else a category default), summed into one agent-proposed order quantity the seller edits. The uplift applies only when an event date exists for the shop (§8.3). |
| RI-FR-3 | The card carries supplier and lead time as agent-proposed fields remembered from prior runs, and a needed-by date. |
| RI-FR-4 | One run, suspended twice in `waiting_external`: a checklist item to place the order; the **"ordered"** report (reference, quantity, expected date); the **"received"** report (quantity, per warehouse if multi-warehouse). **The received-report form is the confirmation**: it states the exact write and the params hash binds the seller-supplied values. |
| RI-FR-5 | Before the write: re-read available and committed stock; check the auto-restock setting; respect the Luôn sẵn hàng committed quantity; validate warehouse allocation. Then exactly one write: Update Inventory. |
| RI-FR-6 | A manual stock rise during the wait closes the run `seller_modified`; nothing is written. |
| RI-FR-7 | Deadline: the reaper policy is the expected date plus a margin; one in-app reminder before the needed-by date (channel per §8.3). |
| RI-FR-8 | End states: `received_and_updated`, `received_partial`, `not_ordered`, `not_received_by_needed_date`, `seller_modified`, `declined`. A partial receipt is a success with a stated shortfall. |

### Non-functional

| # | Requirement |
|---|---|
| RI-NFR-1 | Preconditions (**none met today**): `committed_quantity` persisted (the vendor returns it, three layers drop it) and observed non-zero on a sandbox capture; inventory identity widened to `(shop, sku, warehouse)` (the sync keeps the first warehouse and stops); Update Inventory captured on a multi-warehouse SKU; the attested-report consent kind (params hash over seller-supplied values — today the hash covers the model's arguments only) and `waiting_external` **landed as P0 shared code**; a per-SKU daily demand series (the current forecaster equal-splits shop units across SKUs). |
| RI-NFR-2 | Measure = **stock health, no revenue**: units added ÷ proposed; received before needed-by; days of supply before/after; whether available stock hit zero before receipt. Forecast vs actual is recorded on the run for the next event's uplift. |
| RI-NFR-3 | Stock locks at order placement (`committed_quantity`), never at add-to-cart; the write never reduces available below committed. |
| RI-NFR-4 | No supplier integration exists; the supplier is two reports and a checklist item. |

### Deferred to v2

- The **stranded-stock reconciliation run** and the **auto-restock toggle card** (**⚠ trims ADR-093 d.3** — both are event-time levers on an uncaptured endpoint); the post-event-excess signal (Clear Excess re-cards on its own); the separate event outcome store (v1 records forecast vs actual on the run itself); FBT.

---

## 6. Shared code that v1 needs before any of the four ships

From `PLAN.md` §14 design-order item 0, restricted to what v1 uses:

1. `workflow_key` on runs and playbook resolution from the card (today `approval.py` runs Optimize Product for every card by design); polymorphic bound subject (nullable `product_id`, `subject_type`/`subject_ref`, the active-run index re-keyed); ADR-087's subject-scoped cards; domain-registered tool dispatcher with a subject-generic tool context; shared prompt sections; the **three** gate tests de-pinned (snapshot, budget with its exact token count, playbook-consistency); step input contracts.
2. `waiting_external` run state with a per-workflow reaper policy and the **intervention guard** (Clear Excess, Replenish).
3. The **attested-report** confirmation kind — params hash over seller-supplied values (Replenish).
4. Scheduled card producers per window (Process Order) and per risk signal (Replenish).
5. **Webhook→resume dispatcher** and **scheduled producers** (a beat task per window and per risk signal, under `with_shop_scope`; the one existing card producer has no tenant scope), **an in-app notification record** (the only v1 channel), and **granted-scope persistence** at auth (no OAuth scope is stored today, so OP-NFR-1's degrade branch has nothing to test).
6. **Not in v1:** the deadline clock as a shared escalation service (each v1 workflow uses one in-app reminder at a fixed offset), push/email/Zalo transports, the autonomy ladder, the event spine additions (#13/#14), the event outcome store.

## 7. What "viable" means for v1

**Two proofs, in order.** First the sandbox gate walk below, on data mirrored from the merchant's shop (S-NFR-13). Then the same walk on the connected seller's own shop under their credential, which is the v1 definition of done (S-NFR-11).

A seller can, on the deployed host against the sandbox shop: approve one Optimize Product card and see one discount or one field change land; approve one Clear Excess card, set a goal, and see the discount end when the goal is met; approve one dispatch batch and print its labels; approve one replenish order, report it received, and see stock updated. Each of those four is one gate walk, recorded on its issue, before the workflow is called working.

---

## 8. Scope verification and refinement (2026-09-05)

Four read-only Opus scouts checked this spec against the code, the contracts and the UI. Their
reports are committed under [`scope-verification/`](scope-verification/) — shared code,
Optimize Product + Clear Excess, Process Order + Replenish, and the UX surface. Verdict: **the
write half of every workflow exists and is guarded; the subject, schedule, predicate-fact and
resume halves do not exist.** The corrections above were applied inline; this section records
the precondition ladder and the scope changes that need the owner's decision.

### 8.1 Precondition ladder — P0 shared code (blocks every workflow)

| # | Producer that must exist | Today | Blocks |
|---|---|---|---|
| P0-1 | `workflow_runs.workflow_key` + playbook registry + `approval.py` resolving the playbook from the card | Absent; approval hard-codes Optimize Product for every card (`approval.py:173-187`) | all |
| P0-2 | Polymorphic subject: `product_id` nullable, `subject_type`/`subject_ref`, active-run index on `(shop, workflow_key, subject)`; ADR-087 subject-scoped cards with chained revisions | `product_id NOT NULL`, subject derived from highest revenue at approval, cards unique per shop per workflow | all (Process Order hard-blocked) |
| P0-3 | Domain-registered tool dispatcher with a subject-generic tool context; per-workflow prompt bindings and shared prompt sections; three gate tests de-pinned | Three literal handler dicts bound to `ProductToolContext(product_id=…)`; one prompt binding | CE, PO, RI |
| P0-4 | `waiting_external` (enum, DB CHECK migration, TS union, status-mapping totality test, non-terminal set) + per-run reaper policy resolved from the run's `workflow_key` | Seven states; one global reaper policy | CE, RI |
| P0-5 | Webhook→resume dispatcher: order-/SKU-scoped signal rows from #1, #3, #11, #27, #39, #68 and a consumer that resumes the right run; webhook #63 added to the catalog | Signals persisted shop-scoped; zero readers; #63 absent | CE, RI, PO predicate |
| P0-6 | Seller-supplied inputs: an approve request body, a `seller_inputs` blob in run state, the attested-report confirmation kind hashing seller-supplied values | Approve takes no body; hash covers the model's arguments only | CE (stock goal), RI |
| P0-7 | Scheduled producers under `with_shop_scope` (per window, per risk signal) + per-shop cadence config | No scheduled card or run producer; `action_card_refresh` has no tenant scope | PO, RI |
| P0-8 | In-app notification record + digest payload + Seller Center deep-link template | No transport wired; FCM stub; no email; iOS never uploads its token | PO, CE, RI |
| P0-9 | ~20 new `stop_reason` causes (all ≤ 32 chars) | 16 today; none of the spec's causes | all |
| P0-10 | Granted OAuth scopes persisted at auth + a checker | No scope stored anywhere | OP |
| P0-11 | **Per-tenant production write** under the seller's own credential and RLS: the production-write unlock (#1339) and the W7-bis tenant-isolation fix (#1469), plus the sandbox mirror sync for gate walks (S-NFR-13) | Writes are pinned to one hard-bound sandbox merchant; the runtime still connects as the table owner | all — v1 definition of done |
| P0-12 | **Cross-workflow subject lock + write-lock registry** (S-FR-11): one active run per subject regardless of workflow; endpoint-family locks checked at dispatch | Active-run index is per (shop, product) and the card key includes workflow_key, so two workflows on one product are allowed today | OP ∩ CE ∩ RI |
| P0-13 | **Tracked checklist items** (S-FR-12): a checklist item type on the run with seller-editable text and done state, in the ledger; **deadline view** data feed (S-FR-1) | No checklist concept; no deadline surface | CE, PO, RI |

### 8.2 Precondition ladder — P1 data and captures (per workflow)

| Workflow | Must be true before implementation | Today |
|---|---|---|
| Optimize Product | Both diagnosis endpoints have constants, resource methods, guard entries and a sandbox capture; a `DIRECT_DISCOUNT` create captured; the discount write gets a mutation kind in the impact reader's classifier | Zero hits for "diagnos" in code or contracts; only `FLASHSALE` captured; a discount classifies as nothing and is skipped |
| Clear Excess | `inventory_items` populated (schedule the poll cycle or backfill); per-SKU daily demand from `silver.order_items`; `days_of_supply` and 30-day sell-through helpers; `committed_quantity` persisted; Deactivate captured | The poll cycle that writes inventory is not in the beat schedule; the forecaster equal-splits shop units; both helpers absent |
| Process Order | Sandbox order read path allowlisted; sandbox orders exist; an awaiting-shipment order captured with the SLA fields; Batch Ship walked for real; `get_package` and `get_shipping_document` client methods; raw TikTok order status kept on silver (today `AWAITING_SHIPMENT`/`AWAITING_COLLECTION` both map to "confirmed" and `ON_HOLD` is unmapped); a cancellation transformer | None met |
| Replenish | Inventory identity `(shop, sku, warehouse)`; `committed_quantity` non-zero on a capture; Update Inventory captured on a multi-warehouse SKU; an `update_inventory` ToolSpec over the existing guarded resource (the legacy path works but is not agent-routed); `replenish_defaults` on the card payload for supplier and lead time | Sync keeps the first warehouse and stops; legacy write path only |

### 8.3 Scope changes that need the owner's decision

1. **Margin floor substitute (OP-FR-4, CE-FR-3).** No per-SKU cost exists and the fee-adjusted floor is zero in production (its tests pass on hand-built fixtures). Proposed v1: a seller-set maximum discount per shop as the floor. Alternative: block both discount workflows until a cost column and a producer exist.
2. **Deadline fallback (PO-FR-2).** If the captured order record carries no SLA fields, v1 sorts by the documented cutoff rule (14:00, two working days) instead of "never recompute". Alternative: block Process Order until the fields are observed.
3. **Process Order gate walk.** Requires sandbox orders and a sandbox order read path; both are owner-side or capture work before any slice. Alternative: prove the batch write on the production shop, which is gated on #1339.
4. **Notification channel.** v1 is in-app only. Push, email and Zalo are each a transport slice plus, for push, an iOS token upload; choose one for v2 or none.
5. **Event uplift source (RI-FR-2).** No campaign calendar exists; v1 applies the uplift only when the seller enters an event date on the card, else the baseline alone.
6. **Repeat-consent component.** Shipped and wired in the demo; v1 bans it. Remove, dark-flag, or keep for legacy mock workflows only.

### 8.4 Owner delivery decisions (2026-09-05)

- **Shared code is serialised before the workflow lanes**; the four lanes then run in parallel with disjoint write paths.
- **The first ~10 % of slices in landing order — the P0 shared code and the first Optimize Product slices — are executed by Fable** to set the code standard the later Haiku executors copy; the Haiku review agent reviews them as it reviews every slice. Recorded in `PLAN.md` §14.
- **Sandbox data is mirrored from the connected merchant's shop**, never hand-authored (S-NFR-13).
- **v1 is done at real-seller end-to-end**, not at the sandbox walk (S-NFR-11).

### 8.5 What the ladder means for sequencing

P0-1, P0-2 and P0-3 precede every workflow lane and cannot run in parallel with them; they are
the first slices and the natural home of the Fable-executor exemplars. P0-4 through P0-6 can
land in parallel with the Optimize Product lane, which does not need them. P1 captures are
owner-side or integration slices and should start now, because each one is a fact nobody has
observed yet and the design assumed it.
