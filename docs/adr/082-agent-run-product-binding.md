# ADR-082: Agent run product binding — server-derived from the shop, highest revenue first

**Status:** Proposed
**Date:** 2026-08-21
**Deciders:** grill-with-docs (Architect) with user

**Amends:** [ADR-070](070-agent-safe-sanitization-contract.md) decision 1, whose parenthetical
"the run context (created from the approved ActionCard) holds entity bindings" assumed a
binding that was never built. **Completes:** [ADR-075](075-agent-approval-gate-and-security-prerequisites.md)
decision 1, which specifies "INSERT the `workflow_run` (FK to the card)" without saying where
`workflow_runs.product_id` comes from. **Scope:** W5-A, issue #1222.

## Context

`POST /v1/demo/decisions/{action_card_id}/approve` must create the agent run in one
transaction. It cannot, because nothing on the server records which product the seller
approved:

- `action_cards` carries `shop_id` and `workflow_key` and **no product column**, with
  uniqueness on `(shop_id, workflow_key)` — one row per shop per workflow.
- The scoring pipeline that produces cards carries no product identifier at any point.
  `WorkflowRecommendation` and `_build_payload` (`services/action_cards/persist.py:60-88`)
  are shop-level throughout.
- `workflow_runs.product_id` is **NOT NULL**, FK to `products`, and product identity is
  load-bearing downstream: ADR-073 decision 4's Juli-vs-Juli race guard is a partial unique
  index on `(shop_id, product_id)`.

So the card is shop-scoped and the run is product-scoped, with no bridge. This is the
neighbouring half of the multi-product question already flagged in
[`PLAN.md`](../product/agent-workflow-execution/PLAN.md) — "multi-product Optimize Product —
stacked top-3 card vs N-card cap; `action_cards` unique `(shop_id, workflow_key)` blocks the
cap option without a migration" — deferred to the ActionCard layer and now blocking.

Three options were grilled. Two were rejected:

- **The approve request names the product**, validated against the caller's shop. Keeps a
  human in the loop on which listing is targeted. Rejected: it makes the card an authorization
  for a *workflow* rather than a recommendation about a *product*, and adds a request
  parameter the seller-facing surface would then have to populate.
- **Cards become product-scoped** — `action_cards` gains `product_id`, uniqueness becomes
  `(shop_id, workflow_key, product_id)`, scoring emits per-product cards. This is what every
  downstream document assumes and is the eventual right answer. Rejected *for W5*: it reaches
  into the scoring pipeline, the emission budget, the demo fixtures and the dashboard — a wave,
  not a slice — and relocates rather than answers "which product?", since the recommender would
  then need product-selection logic that does not exist either.

## Decision

1. **The bound product is derived server-side at approval time**, inside the same transaction
   that flips the card and inserts the run. No `product_id` parameter exists on the approve
   request — consistent with ADR-075 decision 1's posture that nothing between "seller clicked
   Approve" and "agent mutated a product" is a caller claim.

2. **The rule is highest revenue first, with a deterministic tiebreak.** Among the caller's
   shop's products, order by `products.revenue` descending, then `tiktok_product_id` ascending,
   and take the first. The tiebreak is not decoration: without it two products with equal
   revenue make the binding depend on row order, and the same card approved twice could target
   different listings for no reason a seller could observe.

   `products.revenue` is the denormalized column added by migration `030`, refreshed by the
   ETL. **It is not a windowed aggregate**, and this ADR does not introduce one — "highest
   revenue" means whatever the last ETL write recorded. A genuinely windowed selection is
   separate data-platform work and is not required for the Optimize Product path.

3. **The binding is a snapshot, not a live lookup.** `workflow_runs.product_id` is written once
   at approval and never re-derived. A run that outlives a revenue change keeps operating on the
   product the seller was shown at the CONFIRM pause. Re-deriving mid-run would let a listing
   the seller never saw receive the write.

4. **A shop with no products is an honest failure.** The approve endpoint returns 409 naming the
   condition rather than creating a run with a null product. Zero products is unreachable on the
   sandbox shop today, and a 500 from a NOT NULL violation would be the wrong way to learn it
   became reachable.

5. **The seller sees the product before any write, at the CONFIRM pause, not at approve.** This
   is the safety property that makes a derived binding acceptable. `workflow.approval_required`
   carries each option's `proposed_change` verbatim (ADR-075 decision 2, #1221), so the seller
   reviews the concrete title or price change — on a named product — and may decline, before
   `ToolExecutor` signs anything. The derivation is not a silent write; it is a silent *choice of
   subject* whose consequences are still consented to individually.

6. **`workflow_runs` gains `action_card_id`.** ADR-075 decision 1 says "FK to the card" and no
   such column exists; without it an `action_card_approvals` row and the run it authorized cannot
   be joined, and P10's five-link outcome chain (recommendation → action → TikTok state change →
   observed outcome → incremental impact) breaks in the middle. Additive, nullable, FK to
   `action_cards`.

## Consequences

- **Recommendation quality gets harder to measure, deliberately.** "Was Juli right?" is asked of
  a card that named a workflow, not a product, so the metric measures workflow selection rather
  than product selection. The product-selection half is unmeasured until cards become
  product-scoped.
- **Multi-product shops get a listing chosen by a rule they never saw.** The rule is documented,
  deterministic and reviewable rather than emergent, and the CONFIRM pause is the backstop — but
  a seller with fifty products has no way to direct Juli at a specific one. This is the accepted
  cost, and it is what makes the product-scoped-card work a real W6 item rather than a nicety.
- **The binding can change between two approvals of the same card** as revenue moves. Two runs a
  week apart may legitimately target different products. Decision 3 confines that to *between*
  runs, never within one.
- Decision 6 requires one additive migration; W5's only schema slice (#1214) has already merged,
  so it needs its own slice.
