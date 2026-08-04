# Issue #682: Real recommendation algorithms — Inventory reorder, Product trend, Livestream script
State: OPEN
Labels: enhancement, PRD

## Problem Statement

Across the three places sellers rely on Juli to tell them what to do next — inventory
replenishment, product listing changes, and livestream follow-up — the recommendation is
either a naive stand-in or missing entirely:

- **Inventory**: when a low-stock warning routes a seller into "Replenish Inventory,"
  Juli asks the seller to type in a quantity themselves. Nothing computes a suggested
  number from how fast that item has actually been selling.
- **Product**: when Juli recommends creating a new "hero" listing or optimizing an
  existing one, it always points at the single highest all-time-revenue product — the
  same product, forever, regardless of whether it's currently trending up, flat, or
  declining. If a price change is suggested, nothing checks whether that cut would leave
  the seller worse off after TikTok's own fees.
- **Livestream**: sellers get no read on how a livestream actually performed relative to
  their own past sessions, and no concrete guidance on what to do differently next time.
  This part of the product is silent today.

None of this is because the data doesn't exist — in every case, real, already-collected
data (sales pace, product-level revenue and conversion trend, TikTok's own fee records,
livestream session stats) is sitting unused, and the actual TikTok Shop platform
documentation on livestream best practice was never consulted.

## Solution

Replace the naive or missing recommendation logic in all three places with real,
data-driven advisories, each reviewed by the seller before anything happens — nothing
here introduces a silent auto-apply:

- **Inventory**: when a seller opens a low-stock replenishment recommendation, Juli
  suggests a specific reorder quantity computed from that item's real recent sales pace,
  with a buffer for how long restocking takes — editable, never silent.
- **Product**: Juli's product recommendation is driven by which product is genuinely
  trending up or down over the last month, not a static "biggest earner ever" pick.
  Declining or inefficient products route to a listing tune-up; strongly trending
  products route to "create a new hero listing modeled on this winner." When Juli
  suggests a price change, it's checked against the shop's real TikTok fee and shipping
  data so a "helpful" suggestion can't quietly leave the seller worse off.
- **Livestream**: after a stream ends, sellers see a performance grade measured against
  their own past streams (not an arbitrary bar), plus a concrete script for their next
  stream — grounded in TikTok's own official livestream coaching framework, optionally
  personalized by AI, always available even when AI isn't.

## User Stories

### Inventory replenishment

1. As a seller, when I open a "Replenish Inventory" recommendation for a low-stock item,
   I want Juli to suggest a specific reorder quantity based on how fast that item has
   been selling, so I don't have to guess a number myself.
2. As a seller, I want the suggested quantity to account for how long restocking takes,
   so I don't run out again while waiting for new stock to arrive.
3. As a seller, I want to freely edit Juli's suggested quantity before approving, so the
   suggestion never locks me in.
4. As a seller, I want Juli to pick the item closest to actually running out first, so
   I'm addressing my most urgent risk.
5. As a seller, if I'd rather replenish a different item than the one Juli picked, I want
   to be able to choose a different product, so the suggestion doesn't box me in.
6. As a seller with a brand-new item with little sales history, I want a reasonable
   fallback suggestion rather than an error or a blank field.

### Product recommendations (Create Hero Product / Optimize Product)

7. As a seller, when Juli recommends creating a new hero listing, I want it modeled on a
   product that's genuinely trending up right now, so I'm scaling a real current winner,
   not an old bestseller that's since gone stale.
8. As a seller, when Juli recommends optimizing an existing listing, I want to understand
   why — declining sales, or traffic that isn't converting — so I know what's actually
   wrong.
9. As a seller, if none of my products show a strong trend either way, I still want a
   product recommendation to review, not nothing, so I always have something to act on.
10. As a seller, I want a "nothing urgent, here's a general tune-up" recommendation to
    read differently from a "this is declining" one, so I'm not alarmed by a false
    problem.
11. As a seller reviewing an Optimize Product recommendation, if Juli suggests a price
    change, I want to see the direction and rough size, so I know what I'm approving.
12. As a seller, I want Juli's price-cut suggestions to never go so deep that I'd
    effectively lose money once TikTok's fees are accounted for, so the suggestion can't
    quietly hurt me.
13. As a seller whose sales volume is up but conversion is down, I want Juli to suggest
    holding price rather than cutting it, since that's a traffic problem, not a pricing
    one.
14. As a seller, I want to edit any suggested price before I approve it, so I stay in
    control.
15. As a seller, when Juli doesn't have enough sales history for a product, I want an
    honest "not enough data yet" state rather than a fabricated trend claim.

### Livestream performance and next-stream script

16. As a seller, after I finish a livestream, I want a performance grade compared to my
    own past streams, so I know if this one did better or worse than usual for my shop.
17. As a seller, I want to know specifically what part of my livestream underperformed —
    pacing, product pitch, urgency — not just a single number, so I know what to change.
18. As a seller, before my next livestream, I want a concrete script suggestion tied to
    whatever part of my last stream was weakest, so I walk in prepared.
19. As a seller whose last livestream went well, I want to be told what worked so I can
    repeat it, not just be shown problems.
20. As a new seller with too few past livestreams to compare against, I want a general
    best-practice script rather than no recommendation at all.
21. As a seller, I want the recommended script to use the same livestream terms and
    stages TikTok itself already teaches, so it feels familiar, not like a new system to
    learn.
22. As a seller, I want the script to read naturally and reference my actual product or
    shop where possible, not a generic canned line, whenever Juli can personalize it.
23. As a seller, if Juli can't personalize the script (for example, daily AI budget is
    used up), I still want a usable, specific script instead of an error or blank state.
24. As a seller, I understand this feature is for before and after a livestream, not
    during it — I don't expect it to replace TikTok's own in-livestream tools while I'm
    actually live.
25. As a seller, I want to know that acknowledging a livestream script recommendation
    never triggers an automatic action on my TikTok account, since Juli can't control a
    livestream on my behalf.

### Cross-cutting

26. As a seller, I want all three of these new recommendations to appear in the same
    review flow I already use elsewhere (see why, see the data, adjust inputs, preview,
    approve), so nothing feels bolted on.
27. As a seller, I never want any of these three recommendations to apply a change
    without my review first.

## Implementation Decisions

- **Inventory reorder advisory**: computed only at the moment a seller opens a low-stock
  replenishment recommendation (not part of the shared daily scoring pass) — reuses an
  existing, previously-unused sales-velocity and low-stock-ranking calculation already
  present in the codebase, extended with a configurable restocking-lead-time buffer and a
  safety-stock buffer that scales with the item's own sales pace. The existing
  replenishment execution step is unchanged — it already accepts whatever quantity it's
  given. See ADR-053.
- **Product target selection**: the existing product-recommendation logic will source its
  target product from a real month-over-month trend comparison, using product-level
  analytics data that's already collected but currently only ever summarized at the
  whole-shop level, replacing the current always-same highest-lifetime-revenue pick.
  Classification into three tiers (strong positive trend / declining-or-inefficient
  trend / no strong signal either way) determines which of the two existing product
  workflows is suggested and how the accompanying explanation is worded — the weak-signal
  tier always still produces a recommendation, worded distinctly from the "something's
  wrong" tier. See ADR-054.
- **Finance data correction (prerequisite for the pricing advisory below)**: the shop's
  Finance/Settlement records currently store two fee fields that have never actually been
  populated by any sync process — they've always read as zero. A schema and mapping
  correction will start capturing the real combined fee and shipping figures TikTok's
  Finance API already returns from the endpoint Juli already polls today, replacing the
  never-populated fields. See ADR-055.
- **Price-direction advisory**: once the Finance data correction above has landed, a
  price cut/hold suggestion becomes available for products flagged as declining, gated by
  a configurable rule: don't recommend a cut that would let TikTok's fees plus shipping
  consume more than a configured share of the sale. This is a fee-based guardrail, not a
  true profit-margin calculation — Juli has no visibility into a seller's product cost.
  See ADR-056.
- **Livestream scoring and script advisory**: reuses an existing, currently-unused but
  functioning livestream grading calculation, unmodified, to score a shop's most recent
  livestream against that same shop's own history. A new three-tier classification
  (matching the product classifier's shape) picks which stage of TikTok's own published
  livestream coaching framework the script should target. A small catalog of script
  templates, organized around that same framework, is selected deterministically; an
  optional AI personalization step may rewrite the selected template within a daily usage
  cap, always falling back to the unmodified template when personalization isn't
  available. A new acknowledgment step records that the seller saw the recommendation —
  it calls no TikTok endpoint, since livestream management isn't something Juli can act on
  today. See ADR-057.
- All three domains render into the recommendation review flow that already exists
  elsewhere in the product (why → supporting data → inputs → preview → approve) — none of
  this introduces a new review pattern, and none of it requires adding fields to the
  shared daily-recommendation-scoring data model, since each advisory is computed only
  when the seller opens the relevant recommendation.
- All four algorithmic pieces (inventory, product trend, livestream scoring, livestream
  script pattern) reconnect logic that was already built and shipped once, under an
  earlier product direction, and went unused only because the navigation surface that
  called it was retired during a later pivot — not because the logic itself was rejected.

## Testing Decisions

- Follow existing repo test conventions (red/green/refactor per domain).
- Inventory advisory: test the reorder-quantity computation against known sales-pace,
  lead-time, and safety-stock inputs, including the zero-sales-history fallback.
- Product classifier: test each of the three classification tiers against known trend
  inputs, including the low-history fallback and the "always produces a recommendation"
  guarantee.
- Finance data correction: test that the corrected mapping populates the new fee field
  from a realistic sample API response, and that the old never-populated fields are gone,
  not silently reintroduced elsewhere.
- Price-direction advisory: test the cut/hold boundary against the configured fee-floor
  rule, including a case where the floor blocks a cut that would otherwise be suggested.
- Livestream scoring: the reused grading calculation already has passing tests as prior
  art and should continue to pass unmodified; new tests cover the classification tiers
  and the template-selection/AI-fallback behavior (verify the fallback path produces a
  usable script when personalization is unavailable or fails).
- Prefer testing the recommendation a seller would actually see over internal computation
  details, consistent with existing tests in the recommendation pipeline.

## Out of Scope

- Real-time in-livestream coaching — TikTok already provides this natively; Juli has no
  real-time livestream data access.
- A true profit-margin (cost-based) pricing floor — no product cost data exists anywhere
  in the system today; would require new seller-provided input, not part of this PRD.
- Per-product (SKU-level) fee/margin data — a richer TikTok Finance data source exists
  that could provide this, but requires new integration work not included here.
- Per-minute livestream retention curves and richer in-stream analytics (viewer trend,
  click-through, follower growth during the stream) — requires a livestream-host
  authentication flow Juli doesn't have today.
- Initial listing price/positioning for a brand-new "Create Hero Product" listing beyond
  selecting which existing winner to model it after — a separate decision, not covered
  here.
- Fulfillment and returns-prevention recommendation workflows — already known gaps,
  tracked separately, not part of this PRD.
- Any change to the recommendation review flow's visual design or copy locks — this PRD's
  advisories render into that surface as it already exists.

## Further Notes

- **Sequencing**: the Finance data correction must land before the price-direction
  advisory. Inventory, product classification, and livestream are independent of each
  other and of the Finance fix, and can ship in any order or in parallel.
- **Rollout**: none of the four pieces touch the shared daily recommendation-scoring
  pipeline, so each can be shipped or rolled back independently without affecting the
  others.
- **Observability**: worth tracking how often the weak-signal fallback paths fire
  (product low-confidence tier, livestream low-confidence tier, AI-personalization
  fallback), to understand how often sellers see the fully-informed version of a
  recommendation versus the fallback version.
- **Follow-ups** (not blocking): per-product fee data via TikTok's richer Finance data
  source; livestream-host authentication for real-time-quality performance data; a true
  cost-based margin floor if seller cost data ever becomes available.
- **Assumptions**: this PRD assumes the existing recommendation review flow is the
  landing surface for all three advisories and needs no changes of its own; assumes the
  shop-level Finance sync already running continues to run as-is, with only the data it
  captures changing.

