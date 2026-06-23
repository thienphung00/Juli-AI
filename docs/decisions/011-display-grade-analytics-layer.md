# ADR 011: Display-grade analytics layer

## Status
Accepted

**Amends:** `system-design.md` § Architecture constraints #3.  
**Supersedes:** Closed-catalog / Copilot-surface workflow framing.  
**Reaffirms:** [ADR-008](008-buyer-behavior-anomaly-scope.md), [ADR-010](010-ml-module-tree-and-trainers.md),
[ADR-013](013-operations-pipeline-spine.md), [ADR-014](014-decision-copilot-app-structure-and-journey.md),
[ADR-012](012-architecture-reconciliation-mvp-vs-target.md).

## Context

The visual layer renders ~19 KPIs as charts plus one-line advisory signals. Two distinct
needs were conflated:

- **Decision-grade ML** — gates a money-moving action behind approval; needs promotion thresholds.
- **Display-grade analytics** — powers charts and advisory signals; never executes.

## Decision

1. **Unified display-grade analytics** from reusable techniques (T1–T8), not one model per KPI:

   | Technique | Implementation | KPIs powered |
   |-----------|----------------|--------------|
   | Forecaster | ETS / Holt-Winters + naive fallback | Revenue, AOV, conversion, inventory KPIs |
   | Ads regressor | ROAS regressor + scale/cut/hold | ROAS, CAC, CTR |
   | Policy rules | Deterministic platform thresholds | SPS, AHR, Violation Points |
   | Statistical anomaly | EWMA / rolling z-score | Fulfillment, cancellation, SLA KPIs |
   | Return-fraud detector | `item_swap` / `empty_return` | Return Request Rate signal |
   | Ranker | Deterministic weighted score-sort | SKU / campaign prioritization |
   | Router classifier | Shop profile → rule set | NEW_SHOP vs MID_LARGE_SHOP |

2. **Fold the three vetted suites** (seller-stage, anomaly, ad-performance) into this layer —
   recycle logic; retire the closed "exactly three suites" framing.

3. **Amend constraint #3.** New display-grade techniques may be added when they power a
   visual-layer KPI, are lightweight, and advisory-only.

4. **Defer sentiment / CSAT to Phase 3.** No buyer review/chat text source in MVP.

5. **Layered model is authoritative:**
   - **Visual layer** → [`visual_layer.md`](../visual_layer.md)
   - **ML layer** → [`ml_layer.md`](../ml_layer.md)
   - **Execution layer** → [`execution_layer.md`](../execution_layer.md)
   - T8 router selects rule set per shop profile; not a UI grouping.

## Rationale

Consolidates seller-money rescope: keeps enforcement aligned with TikTok VN policy while routing alerts through the operations pipeline instead of a standalone service.

## Consequences

- Phase 2 MVP serves display-grade techniques at 08:00 UTC daily batch after API approval.
- Reviewers must enforce advisory-only boundary — display techniques never gate executed actions.
