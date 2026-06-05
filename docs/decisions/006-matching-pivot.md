# ADR-006: Pivot to Creator ↔ Shop Matching + commerce graph

> **SUPERSEDED (historical).** The product was later rescoped from creator↔shop
> matching to **seller-money** workflows (New Seller Copilot, Revenue Leakage
> Detection, Growth Copilot). Creator↔shop matching is now Phase 3+. The current
> plan and design are in [`EXECUTION.md`](../../EXECUTION.md) and
> [`docs/system-design.md`](../system-design.md). This ADR is kept as history.

**Status:** Superseded by the seller-money rescope (see `EXECUTION.md`)
**Date:** 2026-06-03
**Deciders:** Founders / Engineering
**Supersedes:** [ADR-005](005-alerts-module.md) (alerts module)

## Context

Juli-AI was built as a broad TikTok Shop **seller operating system** —
dashboards, orders, inventory, settlements, livestream ops, analytics, and
threshold alerts. This positions us against incumbent analytics tools
(Kalodata, Shoplus, FastMoss) and spreads effort across many features whose
value is *information*, not *decisions*.

The strategy is changing: Juli is **Agentic Commerce Infrastructure for TikTok
Commerce**. The thesis is that the future of commerce is automated
decision-making, and durable value comes from accumulating commerce **graphs**
(Creator, Product, Shop, Trust) that power an autonomous decision engine.

Phase 1 is the wedge:

> Find the best creator for a shop and the best shop for a creator — and output
> the decision (match score + predicted outcome + recommended action).

## Decision

**We will** focus the codebase on Creator ↔ Shop matching and the commerce
graph that feeds it:

- Preserve creator/shop/product **signal collection**, campaign **outcome
  tracking**, the matching/scoring logic, and decision-focused recommendation
  generation.
- Treat every interaction as a graph-strengthening event (nodes: Creator, Shop,
  Product, Campaign; edges: `has_sold`, `potential_match`, `trust_score`,
  `predicted_vs_actual`, …).
- Make recommendations **decision-focused**: match score + justification,
  predicted commercial outcomes (GMV / conversion / engagement / risk), and a
  specific recommended action.

**We will not** build (and have removed): generic dashboards, CRM, inventory
management, finance/settlement software, affiliate-management tooling, or
analytics platforms. We do not compete with Kalodata / Shoplus / FastMoss.

## What changed in the codebase (this pass)

Removals (see `docs/architecture/map.md` → "Removed in the matching pivot"):

- API routers: `analytics`, `settlements`, `inventory`, `orders`, `livestreams`, `alerts`
- Domain module: `catalog/domain/alerts/**` (engine, rules, delivery, channels)
- Backend tests targeting the removed surfaces
- Web pages: order management, inventory management, alert-config (self-contained,
  already redirected, and misaligned)

Kept (Phase-1 aligned or load-bearing for data collection):

- `identity` (auth), `catalog/integrations/tiktok`, `ordering/etl`, `cron_jobs/polling`,
  `webhook`, `shared/utils/data`
- `catalog/recommendations` (already does creator↔product matching + CTAs)
- `catalog/intelligence/{scoring,forecasting}` — **legacy signals** still wired
  into the recommendation engine; to be folded into the `matching/` layer or
  removed when matching is rebuilt graph-first.

Deferred to the implementation (code) phase — intentionally **not** done here:

- Restructuring `shared/utils/data` entities into explicit graph nodes/edges.
- Building the `matching/` (scoring · ranking · prediction) and `agents/`
  (recommendations · actions · decision_logic) layers.
- The outcome **feedback loop** (campaign result → graph edge update).
- Replacing the web seller-OS nav (Livestreams / Trends / Operation) with a
  matching/recommendation-first UI and re-activating Creators / Recommendations.

## Why this architecture (the "because")

- **Speed:** the existing recommendation engine already emits creator↔product
  matches with justification + CTA — the smallest delta to a decision product.
- **Cost:** removing six API surfaces + the alerts module shrinks maintenance and
  test surface, freeing effort for the graph + matching.
- **Scalability / moat:** organizing data as a graph compounds value across
  phases (better matches → trust scoring → autonomous operations).
- **Reliability:** decisions degrade gracefully (stale match values) without
  blocking ingestion or the API.

## Options considered

- **A — Keep the seller-OS, add matching as one more feature.** Rejected:
  reinforces the analytics-platform positioning and dilutes focus.
- **B — Rip out everything and start a greenfield matching service.** Rejected:
  discards working ingestion/auth/recommendation code and the data model.
- **C (chosen) — Trim misaligned surfaces, keep the data-collection + matching
  spine, evolve the data model toward a graph.** Best speed/risk trade-off.

## Consequences

- **Positive:** codebase reflects Phase-1 scope; clear target architecture
  (graphs / matching / agents / data_collection); less debt.
- **Negative:** the web app is temporarily inconsistent (seller-OS nav still
  live while aligned pages are redirected) until the frontend code phase.
- **Follow-ups:** superseded — see [`EXECUTION.md`](../../EXECUTION.md) for the
  current (seller-money) plan.

## Rollout / Migration plan

1. **(done)** Remove misaligned API/domain/test/UI surfaces; realign docs.
2. Restructure data model into graph nodes/edges (additive; no destructive
   migration required for Phase 1).
3. Build `matching/` + `agents/` layers; rebuild recommendations on top.
4. Close the outcome feedback loop.
5. Rebuild the web UI matching-first; retire seller-OS dashboards.
