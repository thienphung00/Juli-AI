# ADR-091: Clear Excess Inventory — TikTok's excess formula, a discount-only lever, and a stock goal the run waits on

**Status:** Proposed
**Date:** 2026-09-03
**Deciders:** grill-with-docs (Architect) with user

**Amends:** [`execution_layer.md`](../product/execution_layer.md) §4 steps 3, 4, 6a and 7;
[ADR-055](055-decision-plan-review.md) d.19's Repeat-consent exclusion list, which bars
`clear_excess_4` on the strength of copy this design removes (d.8).
**Builds on:** [ADR-090](090-optimize-product-realignment.md) — discount-only reprice, a
deterministic price the model may not invent, honest end states — plus
[ADR-087](087-subject-scoped-action-cards-and-card-revisions.md)'s subject taxonomy and card
revisions, ADR-055 d.19's agent-proposed value, and
[ADR-077](077-incremental-impact-measurement.md)'s impact reader.
**Introduces two shared mechanisms:** the **`waiting_external`** run state and the **intervention
guard**, both [`PLAN.md` §14](../product/agent-workflow-execution/PLAN.md) P13 NFR mechanism 4 —
Clear Excess is their first consumer, so they land in design-order item 0, not here.
**Scope:** W10, `PLAN.md` §14 design-order item 2.

## Context

**The baseline markdown is harmful, and it is step 3.** `execution_layer.md:191` applies a
base-price markdown "regardless of which promotion lever is chosen". The promotion journey
([`seller-journeys/promotion.md`](../product/agent-workflow-execution/seller-journeys/promotion.md)
§E) grades it **WRONG-ORDER / harmful** on four counts: a percentage promo recomputes off the new
lower list price, so markdown and promo **compound**; a fixed-price discount **freezes** the list
price, so the update is blocked while it runs; marking down today **raises** the 14-day floor a
later flash sale must beat; and it permanently tightens the L30–180-day thresholds campaign entry
is benchmarked against. ADR-090 removed the base-price write from one workflow; this is the other.

**Clearance has a native end state Juli cannot reach.** The product journey
([`seller-journeys/product.md`](../product/agent-workflow-execution/seller-journeys/product.md)
§C, §D, §F.4) establishes **Sản phẩm thanh lý**: a label that removes the SKU from low/OOS alerts,
adds visibility and opens the app's Clearance section. It has **no Partner API surface**, **cannot
be applied at 0 stock**, and **adding stock silently strips it**. So step 6a — "zero out floor
stock once cleared" — forfeits the mechanism it was reaching for and locks the seller out of
applying it afterwards.

**The two levers are mutually exclusive, and only one of them is evaluable.** Product Discount and
Shop Flash Sale both sit in stacking **layer 1** (single-product), where only one price applies
(§C); both on one SKU is a vendor rejection (`17029022`), so a "pick the lever" rule buys no depth.
Flash Sale is also the one Juli cannot judge: its four eligibility gates — shop rating, VP < 36,
balance > −100 USD, official-account status for the LIVE channels — refresh daily and are not
ingested; its floor is a **contested lookback** (14 days on the newer product page, 30 on the older
LIVE page); its band caps at **50 %** outside holidays; its all-channel window is **10 min–3 days**;
and once `ONGOING` only an extension is accepted (`17029047` / `17029048`). Its own page says "API
không được hỗ trợ" while
[`contract-collection.md`](../integrations/tiktok_api/contract-collection.md) §B-5 holds a sandbox
`FLASHSALE` create that returned `EXPIRED`, not `ONGOING`.

**TikTok already computes the numbers Juli would re-derive.** Quản lý hàng tồn kho publishes the
30-day forecast, **số ngày cung ứng** and the recommended replenishment quantity per SKU (§C).
Inventory Search returns **quantities only**, so Juli must compute days of supply itself — with
TikTok's formula, or the card disagrees with the dashboard in front of the seller.

**Two lifecycle endpoints, one unverified.** `Search Activities`
(`POST /promotion/202309/activities/search`) **is** documented in the Partner API catalog but was
absent from the Promotion API Testing Tool (`execution_layer.md:290-293`) — unverified live.
`Republish Activity` (`POST /promotion/202607/activities/{activity_id}/republish`) revives a
deactivated activity **within 7 days** — what makes deactivation reversible. Deactivate (§B-8) and
Get Activity (§A-25) are captured.

## Decisions

1. **Excess is TikTok's formula at SKU grain; the card is per product.**
   `days_of_supply = available ÷ 30-day daily forecast` — TikTok's own formula, computed by Juli
   because Inventory Search returns quantities only. A SKU is excess when
   `days_of_supply > threshold` (default **90**, seller-adjustable) **and** 30-day sell-through is
   below its threshold. Excluded outright: campaign-locked stock, creator-reserved stock, the
   **Luôn sẵn hàng** committed quantity, SKUs already labelled **Thanh lý**, and SKUs in any live
   promotion Juli created. The card's subject is the **product** (ADR-087 d.5 taxonomy); its
   evidence is the excess SKUs and their quantities. Borrowing the platform's formula is what keeps
   Juli's number and Seller Center's number the same number. *Rejected:* the T1 forecaster's risk
   signal as the trigger — its threshold is invisible to the seller and its output disagrees with
   the dashboard.

2. **Product Discount is the only lever; Flash Sale is deferred behind three conditions.** The
   run creates a `DIRECT_DISCOUNT` (percent) activity through the same `create_product_discount`
   tool ADR-090 d.1 introduces, 30-day default window. Flash Sale becomes a gated **second** lever
   only when all three hold: (a) a production VN `FLASHSALE` create is observed reaching `ONGOING`;
   (b) a reliable per-SKU 30-day price low exists; (c) the four eligibility signals (VP < 36,
   balance > −100 USD, official-account status, the rating threshold) are ingested. Since the two
   levers cannot coexist on a SKU, a second lever adds no reach — only an eligibility check Juli
   must guess at and an activity it could not edit once live. *Rejected:* shipping both levers with
   a rule that chooses between them.

3. **Deterministic price, validator at dispatch, vendor rejection as the last backstop.** A
   pricing rule computes, per SKU, a discount **envelope** and one **recommended depth** from the
   T9 fee-adjusted margin floor ([ADR-066](066-t9-fee-adjusted-price-rule.md)), the 1–90 % band,
   sell-through and days of supply. Depth is computed **off list price, never off a prior
   markdown**. The model chooses which SKUs to include and how to word the proposal, and calls the
   tool with **exactly** the computed parameters — ADR-075's params-hash consent binding is what
   makes "exactly" checkable. Before CONFIRM the runner validator re-checks eight rules: (1) depth
   inside the 1–90 % band; (2) resulting price at or above the margin floor; (3) window inside
   10 minutes – 30 days; (4) activity price strictly below list, computed off list; (5) no stacking
   collision — Search Activities if captured, otherwise nothing to check and the vendor decides;
   (6) stock buckets, so excluded quantities are never counted as sellable; (7) purchase limits
   `-1` or `1..99`, variation level `-1`; (8) batch ≤ 300 items. Plus a **disclosure check**: the
   `proposed_change` must state the 30-day window, the ≥ 1-day hold before the traffic benefit
   lands, and that this discount **lowers the floor a future flash sale must beat**. A clampable
   violation triggers **one** forced re-proposal naming the bound that was hit; a non-clampable one
   ends the run `completed` with a cause. A vendor rejection *after* the validator passed is a real
   failure — surfaced, never silently retried. *Rejected:* letting the vendor be the validator —
   that spends the seller's approval on a change that then fails, and the vendor never checks
   Juli's margin floor.

4. **The stock goal is set at approval; the run closes out on the 30-day expiry or on the goal;
   reaching the goal deactivates without a fresh confirmation.** The Stage B card carries an
   **agent-proposed stock goal** (≈ 30 days of supply) — ADR-055 d.19's rule that the agent
   pre-commits a value for every field, including the ones the seller decides. It is
   seller-editable, validated `0 ≤ goal < sellable-after-exclusions`, measured on the **available**
   bucket, snapshotted with the approval, carried in run state and **restated at CONFIRM**. When
   `units_to_clear = available − goal` is ≤ 99, `quantity_limit` is set to `units_to_clear` so
   **TikTok** enforces the goal; above 99 the limit is unlimited and Juli enforces it by event.
   After the write the run enters **`waiting_external`** — reaper policy = the discount window plus
   a margin, never `waiting_approval`'s 4-hour timeout, whose paused wall clock is load-bearing for
   consent expiry ([ADR-073](073-agent-execution-loop-and-write-path-hardening.md)). Two conditions
   resume it:
   **inventory webhook #27 / #68 with available ≤ goal** → resume → **Deactivate Activity with no
   fresh CONFIRM** (the seller defined the stopping condition at approval and saw it again at
   CONFIRM; deactivation sets no price and is reversible for 7 days via republish), notifying
   *"Stock reached your goal of N; Juli ended the discount. M units remain."*; and **activity
   webhook #39 `EXPIRED` with stock above the goal** → `completed`, with a card revision through
   ADR-090 d.6's no-duplicate path proposing a republish or nothing. `EXPIRED` with the goal
   already met emits nothing. The **Thanh lý** label is presented at approval as a **human checklist
   item** beside the discount: Juli can neither set nor verify it, and says so — the label cannot be
   applied at 0 stock, which is exactly why the discount, not a stock write, is the mechanism.
   *Rejected:* a card asking the seller to confirm the goal was reached — it asks a set condition
   twice, and a missed card leaves the discount running below the goal. Also rejected: automatic
   deactivation under level-1 consent, which does not exist server-side.

5. **Any seller intervention closes the workflow.** A change to the activity that did not
   originate with Juli — price or depth, product set, window, or the seller deactivating it — or
   an upward stock move on the cleared SKUs ends Juli's management of that activity. Detection: on
   activity-change webhook **#63** or status webhook **#39**, re-read the activity and compare it
   to the **creation snapshot**; on an inventory webhook showing an increase; list-price edits are
   caught on the next reconcile, whose latency the copy states plainly. Juli changes nothing, ends
   `completed` with cause `seller_modified`, says *"You changed this promotion, so Juli stopped
   managing it. It stays as you set it."*, and **never re-issues a card for that activity** — a new
   card needs a new basis. Generalised, this is the **intervention guard** of `waiting_external`:
   every suspending workflow snapshots what it created and closes on external divergence, because a
   run that keeps managing a thing the seller has taken back is the failure mode a long wait
   invents. *Rejected:* reconciling Juli's intent onto the seller's edit — it overwrites a
   deliberate human act with a stale plan.

6. **Success is goal progress; impact is revenue on the cleared SKUs; the card KPI stays AOV and
   Stock Health is the run's internal measure.** The did-the-job fact is
   `units cleared ÷ units to clear` — a fact, unhedged, feeding execution quality in `CONTEXT.md`'s
   four-metric separation. The **impact reading** is revenue on the cleared SKUs against the
   pre-discount baseline through ADR-077's existing reader, hedged as an estimate like every other
   reading. The card's KPI tie is **unchanged — AOV**, per ADR-055 d.15's `analyticsMetricKey`
   table; ADR-049's five-KPI catalog is **not** amended here. **Stock Health** (days of supply) is
   the run's *internal* measure instead: days of supply **before and after** is recorded on the run
   and stated in the completion copy, where it is the honest reading of what the discount did to
   the stock position, without spending the one card KPI slot on a metric outside the five.
   **Margin recovered is out of scope** until a per-SKU cost exists.
   *Observed, not resolved here:* the backend's `KPI_WORKFLOW_KEYS` already maps `clear_excess_4`
   to `dsi` and `inventory_turnover` while the card ties to AOV — a pre-existing disagreement
   between two tables that predates this design and that this ADR neither creates nor fixes.
   *Rejected:* moving the card KPI to Stock Health — it would require amending ADR-049's five-KPI
   cap (Stock Health is not one of the five) for a reading the run already carries internally.

7. **Honest end states**, reusing ADR-090 d.7's vocabulary and
   [ADR-088](088-consent-pause-is-a-runner-guarantee.md)'s terminal tool with a cause:

   | Cause | Meaning |
   |---|---|
   | `goal_met` | Stock reached the goal; the activity was deactivated |
   | `expired_stock_remaining` | The 30-day window ended with stock above the goal |
   | `expired_goal_met` | The window ended and the goal had already been met |
   | `seller_modified` | Decision 5 — the seller changed the activity or the stock |
   | `already_in_promotion` | Every excess SKU is in a live layer-1 promotion |
   | `nothing_sellable` | After exclusions, no sellable excess remains |
   | `no_safe_discount` | The clamped depth fell below usefulness against the margin floor |
   | `declined` | The seller declined |

   A vendor failure after a passing validator stays on the existing terminal failure path; a run
   that wrote nothing produces **no impact reading** and counts separately from a failure.
   *Rejected:* one generic "nothing to do", which makes eight different facts indistinguishable.

8. **The irreversibility copy goes, and with it the no-auto-act bar.** The shipped `clear_excess_4`
   seller copy — *"Việc xoá tồn kho về 0 là bước không thể hoàn tác — chỉ thực hiện sau khi có xác
   nhận thực tế"* — describes the **stock write** that decision 4 deletes. In this design the only
   write is a **30-day Product Discount**: deactivation ends it (d.4) and `Republish Activity`
   revives it within 7 days. Nothing here is irreversible and nothing waits on a physical count, so
   the statement is not merely redundant — it is **false**, and false safety copy is worse than
   none. It is removed, and with it the **No-auto-act promise** it constitutes (`CONTEXT.md`), so
   `clear_excess_4` becomes **eligible for Repeat consent** once the autonomy ladder exists. The
   first pre-approvable act is the **goal-triggered deactivation**, which d.4 already performs with
   no fresh CONFIRM; ending an expired activity follows later. What stays consent-bound is
   unchanged: the discount create still pauses at CONFIRM, params-hash bound (d.3), because setting
   a price never leaves level 0 of `PLAN.md`'s ladder.
   *Rejected:* keeping the sentence as a generic caution — it names a step this workflow no longer
   has, and a promise the product cannot point at is a promise it cannot keep.

   > This **narrows [ADR-055](055-decision-plan-review.md) d.19**, in the opposite direction from
   > [ADR-090](090-optimize-product-realignment.md) d.6: ADR-090 takes `optimize_product_2` **out**
   > of the Repeat-consent-eligible set, and this decision puts `clear_excess_4` **in**. d.19's
   > exclusion of `clear_excess_4` was assessed against the stock write, which no longer exists.

## End-to-end steps

**Stage A — monitoring; Stage B — approval**

| # | Step | Mechanism |
|---|---|---|
| A1 | Read stock per SKU | `POST /product/202309/inventory/search` — quantities only |
| A2 | Compute days of supply and 30-day sell-through | TikTok's formula (d.1), Juli-side |
| A3 | Apply exclusions | campaign / creator / Luôn sẵn hàng / Thanh lý / live Juli promotion |
| A4 | Emit or suppress the product-subject card | ADR-087 standard path; a named `suppressed_reason` when nothing qualifies |
| B1 | Card shows excess SKUs, quantities, the recommended depth per SKU, and the **agent-proposed stock goal** (≈ 30 days of supply, seller-editable, `0 ≤ goal < sellable`) | d.3, d.4 |
| B2 | Approval snapshots goal + depths + basis; the **Thanh lý** checklist item is shown as a step only the seller can perform | ADR-075 approval gate |

**Stage C — run**

| # | Step | Mechanism |
|---|---|---|
| C1 | Re-read inventory and basis | ADR-073 basis snapshot |
| C2 | Collision check | Search Activities if captured; otherwise declared unchecked |
| C3 | Model selects SKUs and wording, calls `create_product_discount` with the computed parameters | d.3 |
| C4 | Validator: eight rules + the disclosure check; one forced re-proposal on a clampable violation | d.3 |
| C5 | CONFIRM pause, params-hash bound, goal restated | ADR-075 d.2, ADR-088 |
| C6 | Create the `DIRECT_DISCOUNT` activity; attach products (`PUT .../activities/{id}/products`) | §B-5, §B-7 |
| C7 | Set `quantity_limit = units_to_clear` when ≤ 99; otherwise unlimited, Juli-enforced | d.4 |
| C8 | Enter **`waiting_external`**, reaper = window + margin | d.4 |

**Stage D — suspended and close-out**

| # | Trigger | Outcome |
|---|---|---|
| D1 | Inventory #27 / #68, available ≤ goal | Resume → Deactivate Activity (§B-8), no fresh CONFIRM → notification → `goal_met` |
| D2 | Activity #39 `EXPIRED` | Stock above goal → `expired_stock_remaining` + card revision (republish or nothing); goal met → `expired_goal_met`, no card |
| D3 | Intervention: #63 or #39 divergence from the creation snapshot, an inventory increase, or a list-price edit seen on reconcile | Change nothing → `seller_modified`, no future card for that activity |

**Stage E — measurement.** E1 `units cleared ÷ units to clear`, unhedged, into execution quality;
E2 revenue on the cleared SKUs vs the pre-discount baseline through the ADR-077 reader, hedged as
an estimate; E3 the card's KPI tie stays **AOV** (ADR-055 d.15), while **days of supply before and
after** is recorded on the run and stated in the completion copy as the run's internal measure.

## Consequences

- **Tool set.** Reuse `create_product_discount` (ADR-090 d.1); add `deactivate_activity` (WRITE,
  §B-8) and `search_activities` (READ/AUTO, only if it captures); `republish_activity` arrives
  later with the D2 revision. No base-price write and no stock write in this workflow's allowlist.
- **Shared code lands first.** `waiting_external`, its reaper policy and the intervention guard are
  `PLAN.md` design-order item 0 work; Clear Excess is their first consumer and must not fork a
  private version.
- **Card and approval shape.** A `stock_goal` field on the card, snapshotted into the approval and
  carried in run state; a checklist item type for the Thanh lý step Juli cannot perform.
- **No KPI catalog change.** `clear_excess_4`'s `analyticsMetricKey` stays **AOV** (ADR-055 d.15)
  and ADR-049's five-KPI cap is untouched. What is new is a **days-of-supply before/after** pair
  recorded on the run and rendered in the completion copy (d.6).
- **Copy removal is its own slice.** The `clear_excess_4` irreversibility statement and the
  Repeat-consent exclusion built on it live in code, not in this ADR. The slice edits
  `apps/demo/src/lib/recommendations.ts` (the `clear_excess_4` entry's `risks` field),
  `apps/demo/src/lib/repeat-consent.ts` (flip `clear_excess_4` to `eligible: true`, clear its
  `note`), `apps/demo/src/lib/workflows/clear-excess/review.ts` and
  `apps/demo/src/lib/workflows/clear-excess/execution.ts` (the zero-inventory step copy, which d.4
  deletes outright), and the four tests that currently assert the string —
  `apps/demo/src/lib/workflows/clear-excess/__tests__/{plan,review,execution}.test.ts` and
  `apps/demo/src/__tests__/repeat-consent.test.tsx`. `packages/contracts` carries none of this
  copy. Removing the sentence without also removing the stock write it describes would be the
  wrong order — the slice follows the d.4 rewrite.
- **`execution_layer.md` §4 rewrite** (its own slice): step 3 deleted; step 4 becomes a
  `DIRECT_DISCOUNT` create behind the validator; step 6a becomes the Thanh lý checklist item;
  step 7 becomes goal-or-expiry close-out.
- **Contract captures needed** on the sandbox: `Search Activities` (does it exist?), a
  `DIRECT_DISCOUNT` create, a deactivate, later a republish. Until Search Activities captures,
  validator rule 5 is declared unchecked and the vendor is the only lock signal — ADR-090 d.2's
  posture, unchanged.
- **Risk.** Two unverified facts: whether Search Activities exists live, and whether the inventory
  webhooks fire fast enough that D1 does not lag the goal by hours. Neither touches decisions 1–3
  or 5–7; both sit inside decision 4's resume path, which degrades to the 30-day expiry if the
  webhook never comes.
