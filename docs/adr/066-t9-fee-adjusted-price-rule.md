# ADR-066: T9 fee-adjusted price rule — Optimize Product price_update from real Settlement fees

**Status:** Accepted
**Date:** 2026-08-03
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-063](063-t10-inventory-reorder-engine.md) (lazy-compute-at-Inputs-step
pattern), [ADR-064](064-product-performance-classifier.md) (Fix classification routes here),
[ADR-065](065-finance-statement-fee-mapping-fix.md) (**hard prerequisite** — this ADR is
not buildable until ADR-065 ships; `fee_amount`/`shipping_fee` must be real before this
rule can read them).
**Does not change:** `run_optimize_product_chain` — `price_update` remains an optional
payload key it already accepts unchanged; `create_hero_product_1` pricing (out of scope,
see Consequences).

## Context

ADR-064's Product Performance Classifier routes a product to Optimize Product on **Fix**
(GMV/conversion decline, or GMV up with conversion down) but does not decide *whether or
how much* to move price — that's `price_update`, the one field
`run_optimize_product_chain` doesn't auto-fill from TikTok's own suggestions API (title/
description are already handled there).

A true profit-margin floor (price minus COGS) cannot be computed — `Product` has no cost
column anywhere in the schema, and Juli has no visibility into seller sourcing cost. But
ADR-065 makes a real, shop-level **fee-adjusted** floor possible: `Settlement.fee_amount`
+ `Settlement.shipping_fee`, real Partner-API-synced data (as of ADR-065), give an actual
"how much of each sale survives TikTok's cut" rate — not profitability, but a legitimate,
data-backed constraint on how far a price cut should go.

## Decision

**Price direction is a deterministic rule on real per-product trend (from ADR-064's
classifier inputs) gated by a real, shop-level fee floor (from ADR-065's corrected
`Settlement` data).**

- **Inputs (all real):**
  - `gmv_trend`, `conversion_trend` — already computed for the ADR-064 classification of
    this product; reused, not recomputed.
  - `fee_rate` — `avg(|fee_amount| + |shipping_fee|) / revenue_amount` over recent
    `Settlement` rows for the shop (shop-level; `Settlement` has no order/product FK, so
    this cannot be per-product — same limitation noted in ADR-063/064's data model).
- **Rule:**
  - Fix — demand & efficiency (GMV↓, conversion↓): recommend a price **reduction**, only
    if `(1 - fee_rate) ≥ min_retained_rate` still holds after the proposed cut.
  - Fix — inefficient traffic (GMV↑, conversion↓): recommend price **hold** — volume is
    already there; a cut would erode the fee-adjusted margin further without addressing
    the actual conversion problem (likely listing/creative, which TikTok's own suggestion
    API already targets via title/description).
  - Scale (routed to Create Hero Product, not this rule): no `price_update` here — pricing
    for a brand-new listing is a separate, out-of-scope decision (see Consequences).
- **Constant (config, not derivable from data — same category as T10's `lead_time_days`):**
  `min_retained_rate = 0.70` — don't recommend a cut that would push the seller's
  fee-adjusted take-home below 70% of the sale price.
- **Wiring:** computed lazily at the Optimize Product Inputs-review step (same pattern as
  ADR-063/064), only for Fix-classified products; prefills `price_update` direction +
  magnitude, editable, "Gợi ý bởi Juli" glow, never silent.

## Consequences

- T9 only fires for Fix classifications; Explore-classified products (ADR-064) never get
  a `price_update` — Optimize Product still runs, just without a pricing claim the data
  doesn't support.
- `fee_rate` is shop-wide, not per-product — every product's price rule is gated by the
  same constant. A genuinely per-product fee-adjusted floor requires the SKU-level `Get
  Transactions by Order` ingestion flagged (and deferred) during this planning pass —
  documented here as the natural next upgrade, not required to ship this rule.
- Create Hero Product's initial listing price is explicitly **not** covered by this rule —
  it's a new-listing pricing decision (positioning a brand-new SKU), not a price *move* on
  an existing one; out of scope for this ADR, flagged as a follow-up decision.
- `min_retained_rate` is a global constant at launch, same posture as T10's `lead_time_days`
  — a per-shop config surface is deferred until there's a reason to differentiate.

## Options considered

| Option | Outcome |
|--------|---------|
| Build T9 on the (broken) `platform_commission`/`affiliate_commission` split | Rejected — those columns are always zero (ADR-065); would have shipped a rule that never actually cuts price |
| Use a pure configured margin floor with no real data at all | Rejected — real, reachable data exists (`Settlement.fee_amount`/`shipping_fee` once ADR-065 lands) and the user directive favors real data over a pure guess whenever reachable |
| Compute `fee_rate` per-product now via `Get Transactions by Order` | Rejected for this pass — real new integration (new scope, new client, per-order rate-limited calls); logged as future upgrade, not blocking |
| **Shop-level `fee_rate` from corrected `Settlement` + configured `min_retained_rate` (chosen)** | Real data, minimal scope, consistent with T10/ADR-064's posture |
