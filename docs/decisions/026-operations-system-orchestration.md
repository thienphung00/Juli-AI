# ADR 026: Operations-System Orchestration (Phase 1.8)

## Status
Accepted

## Context

- Product refined Juli AI into a focused **AI Operations System**: collect operational
  data, evaluate shop health, classify shop profile, recommend ranked executable
  workflows, explain via copy layer, gate on user approval, route to Copilot execution,
  and track outcomes — with strict traceability (no orphan data, metrics, or workflows).
- Phase 1.6 (listing) and Phase 1.7 (leakage) delivered **executable** mock workflows
  for subsets of the validated catalog. Phase 1 UI (P1-4 growth) remains task-card mock
  only. No spine tied classification → health → ranking → unified approval → outcome
  tracking.
- [`EXECUTION.md`](../../EXECUTION.md) originally jumped from Phase 1.7 to Phase 2.
  Real TikTok API wiring, ML inference, Ollama copy, and live executors remain Phase 2+.
- SPS and full AHR/VP numeric scores are **not** exposed via Partner API today
  ([`integration-audit-2026-06.md`](../tiktok_api/integration-audit-2026-06.md) §7);
  P1.8 uses mock fixtures; P2 degrades explicitly per `health_data_source` contract.
- Scoped inventory signals (level, sales velocity, lead time) are required only for
  Stockout Prevention + Product Scaling — **signals, not inventory management**.

## Decision

- We will: insert **Phase 1.8** (Weeks 11–13) between Phase 1.7 and Phase 2 — mock
  **operations-system orchestration** spine with six **validated workflows only**
  (no expansion without explicit evaluation).
- We will: use two shop profiles — `NEW_SHOP` | `MID_LARGE_SHOP` — with copilot
  surfaces:
  - **NEW_SHOP** → **New Seller Copilot** (2 workflows): NPL, Minimize Violations.
  - **MID_LARGE_SHOP** → **Growth Copilot** (Budget Optimization, Product Scaling) +
    **Loss Prevention** under Revenue Leakage (Refund Spike Detection, Stockout
    Prevention).
- We will: implement the pipeline stages (mock loaders; stable envelopes for P2 swap):

  ```
  Data Collection (unified_operational_data_model)
    → Health Check (health_check_results)
    → Shop Profile Classification (shop_profile)
    → Workflow Recommendation & Ranking (workflow_recommendations)
    → LLM Reasoning (reasoning_summary — rules-only in P1.8)
    → User Approval (approved_workflows)
    → Copilot Execution (workflow_results)
    → Outcome Tracking (workflow_outcome_metrics)
  ```

- We will: map **Refund Spike Detection** to all four P1.7 leakage executable
  sub-journeys (`return_spike`, `buyer_cancellation_cluster`, `refund_cluster`,
  `return_window_policy`) — one validated workflow, multiple task-type routes.
- We will: in P1.8, route **executable** approvals only to built panels:
  - NPL → `ListingWorkflowPanel` (P1.6)
  - Refund Spike Detection → `LeakageWorkflowPanel` (P1.7, by task type)
  - All other validated workflows → recommendation card + reasoning; **approve = no-op**
    until Phase 2 executors (Violations, Stockout, Budget Optimization,
    Product Scaling).
- We will: enforce architecture constraints (non-negotiable):
  1. No new workflows without explicit necessity + fit evaluation.
  2. No new shop profiles without a business case.
  3. No additional ML models unless required by an existing workflow and vetted.
  4. Data traceability: every collected datum → ≥1 workflow.
  5. Metric traceability: every health indicator → ≥1 workflow decision.
  6. Recommendation traceability: every recommendation → ≥1 validated workflow.
  7. Prefer explicit rules over implicit inference.
  8. Explainability: Why + Expected Impact on every recommendation.
- We will: defer **MID_LARGE_SHOP impact threshold** numeric value to Product lead
  (required before P1.8-4 ships); P1.8 mock may compute impact scores without
  filtering until threshold is set.
- We will: add Phase 2 slices P2-11…P2-15 for live pipeline, scoped inventory,
  and deferred workflow executors (see [`EXECUTION.md`](../../EXECUTION.md)).
- We will not: collect data or compute health metrics unused by the six workflows;
  invent workflows in the copy/reasoning layer; retry failed execution without explicit
  user approval; escalate to additional workflows on failure; build inventory/finance
  management features.

## Why this architecture

- **Speed:** Reuses P1.6/P1.7 modal workflows and P1-4 growth fixtures; P1.8 adds
  orchestration shell + rules-only ranking/reasoning — no backend or LLM spend.
- **Cost:** Mock-only phase validates operations UX before P2 API + Ollama investment.
- **Scalability:** Stable JSON envelopes (`unified_operational_data_model`,
  `health_check_results`, `workflow_recommendations`, etc.) allow P2-11 loader swap
  without UI stage rewrites.
- **Performance:** Rules-based classification, health, and ranking are deterministic
  and fast for interactive approval flows.
- **Reliability/Operability:** Traceability constraints prevent scope creep; no-op
  routing for undeferred executors avoids false “executed” states; P2 gates API field
  exposure before live health/SPS/inventory collection.

## Options considered

- **Option A: Skip P1.8; wire orchestration directly in P2** — faster calendar but
  couples UX validation to API availability. **Rejected.**
- **Option B: Mock orchestration spine in P1.8 (chosen)** — validates end-to-end
  operations UX on fixtures; P2 swaps data sources.
- **Option C: Build standalone panels for all six workflows in P1.8** — too much
  scope before API verification. **Rejected** — no-op cards for deferred executors.
- **Option D: Refund Spike = `return_spike` only** — underuses P1.7 investment.
  **Rejected** — user chose all four leakage types as sub-journeys under one workflow.

## Consequences

- **Positive:** Single operations narrative; profile-gated recommendations; clear P2
  executor backlog; inventory scope narrowly justified.
- **Negative:** Growth and deferred New-Shop / loss-prevention workflows feel
  “incomplete” until P2-13/14/15;
  impact threshold blocks P1.8-4 filter until Product sets value; SPS/AHR live data
  may remain proxy/unavailable post-P2-1.
- **Follow-ups:** P1.8-1…P1.8-7 slices; Product lead impact threshold; fixture
  traceability map; `web/src/lib/operations/*` modules per [`map.md`](../architecture/map.md).

## Rollout / Migration plan

1. **P1.8:** Mock fixtures + rules pipeline + unified approval shell; executable
   routing to listing + leakage panels only; outcome metrics mocked.
2. **P2-11:** Swap mock loaders for live poll + inference + Ollama reasoning.
3. **P2-12…P2-15:** Live inventory signals + deferred workflow executors behind
   approval queue pattern (symmetric with P2-7/P2-9).

## Appendix A — Validated workflow catalog

| `workflow_id` (stable) | Profile | Copilot surface | P1.8 execution | P2 executor |
|------------------------|---------|-----------------|----------------|-------------|
| `npl` | NEW_SHOP | New Seller | `ListingWorkflowPanel` | P2-7 / P2-8 |
| `minimize_violations` | NEW_SHOP | New Seller | Card + no-op | P2-13 |
| `budget_optimization` | MID_LARGE_SHOP | Growth | Card + no-op | P2-14 |
| `product_scaling` | MID_LARGE_SHOP | Growth | Card + no-op | P2-14 |
| `refund_spike_detection` | MID_LARGE_SHOP | Revenue Leakage (loss) | `LeakageWorkflowPanel` (4 sub-journeys) | P2-9 / P2-10 |
| `stockout_prevention` | MID_LARGE_SHOP | Revenue Leakage (loss) | Card + no-op | P2-12 / P2-15 |

## Appendix B — Outcome tracking success criteria

| Workflow | Metric | Period | Success criteria |
|----------|--------|--------|------------------|
| Add New Product Listings | SPS change | 7d post-publish | ≥ +5 SPS points |
| Minimize Violations | AHR improvement / violation count | 7d | ≥ +10 AHR points OR violation count ↓ |
| Budget Optimization | ROAS / revenue change | 7d | ROAS +15% OR revenue +10% |
| Product Scaling | Revenue per scaled SKU | 14d | ≥ +20% revenue for scaled products |
| Refund Spike Detection | Refund rate reduction | 7d | Refund rate returns to baseline |
| Stockout Prevention | Stockouts avoided | 30d | 0 unplanned stockouts |

Cadence: real-time execution status → daily preliminary → weekly full assessment →
monthly aggregate.

## Appendix C — Workflow execution preconditions (Phase 2 target)

Summarized from product spec; P1.8 mocks precondition flags only.

- **NPL:** Product data, supplier validated, category not restricted.
- **Minimize Violations:** Active violations + categories identified.
- **Budget Optimization:** ≥2 active campaigns, ≥7d performance data.
- **Product Scaling:** Top products identified, sufficient inventory to scale.
- **Refund Spike Detection:** Refund rate spike >20% above 30d average.
- **Stockout Prevention:** Inventory trending toward stockout, lead time available.
