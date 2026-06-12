# PRD: MVP 1.8 — Operations-System Orchestration (P1.8-1…7)

> **Phase:** 1.8 (Weeks 11–13) · **Slices:** P1.8-1 through P1.8-7 · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/system-design.md`](../../system-design.md) § Operations-system pipeline · **ADR:** [ADR-026](../../decisions/026-operations-system-orchestration.md)
>
> **Related:** P1.8-8 design-system polish is scoped separately in [`PRD.md`](PRD.md) / GitHub [#174](https://github.com/thienphung00/Juli-AI/issues/174).
>
> **Exit gate:** E2E pipeline for both `NEW_SHOP` and `MID_LARGE_SHOP` on mock data — classify → health check → ranked recommendations → reasoning → approval → routed execution → outcome view; full traceability; recommendations never outside validated catalog; unified approve-all / selective / reject-with-reason.

---

## Problem Statement

Phase 1 delivered three copilot workflows as **separate demo surfaces**: PersonaSwitcher picks a persona → `classifySellerStage(new|leakage|growth)` → one copilot panel + task queue. Phase 1.6 and 1.7 added **executable** modal journeys for listing (`list_products`) and four leakage task types, but the seller home still treats each workflow as an isolated destination — not an operations system.

Sellers operating a real shop need one spine: collect operational signals, evaluate shop health, classify whether they are a **new shop in probation** or a **mid/large graduated shop**, receive ranked explainable workflow recommendations from a **validated catalog of six workflows only**, review deterministic reasoning, approve selectively or in bulk, execute where panels exist, and track outcomes over time.

Without Phase 1.8 orchestration on mock data, Phase 2 would wire TikTok APIs into disconnected UIs. Product cannot validate the operations narrative, traceability constraints, or approval→execution routing before API and Ollama investment.

---

## Solution

Replace `SellerHomeShell`'s "pick one copilot panel" layout with an **operations pipeline home** that orchestrates mock data through stable JSON envelopes, while **embedding existing P1.6/P1.7 executors** as execution destinations (not the primary layout).

```
PersonaSwitcher (demo input)
  → unified_operational_data_model
  → shop_profile (NEW_SHOP | MID_LARGE_SHOP)
  → health_check_results
  → workflow_recommendations (ranked, max 6 validated workflows)
  → reasoning expansion (rules-only Why / Impact / Next Steps)
  → unified approval gate (approve all / selective / reject-with-reason)
  → route: NPL → ListingWorkflowPanel | Refund Spike → LeakageWorkflowPanel | others → no-op toast
  → workflow_outcome_metrics (cadence tabs)
```

**Six validated workflows only** ([ADR-026](../../decisions/026-operations-system-orchestration.md)):

| Profile | Workflow | P1.8 execution |
|---------|----------|----------------|
| NEW_SHOP | Add New Product Listings (NPL) | Executable → P1.6 listing panel |
| NEW_SHOP | Minimize Violations | Card + reasoning; approve = no-op |
| MID_LARGE_SHOP | Budget Optimization | Card + reasoning; approve = no-op |
| MID_LARGE_SHOP | Product Scaling | Card + reasoning; approve = no-op |
| MID_LARGE_SHOP | Refund Spike Detection | Executable → P1.7 leakage panel (4 sub-journeys) |
| MID_LARGE_SHOP | Stockout Prevention | Card + reasoning; approve = no-op |

**Traceability (non-negotiable):** every mock datum → ≥1 workflow; every health indicator → ≥1 workflow decision; every recommendation → ≥1 validated workflow; copy layer never invents workflows.

**Growth Copilot (P1-4)** remains reference UI only — P1.8 does **not** route Budget Optimization or Product Scaling approvals into `GrowthCopilotPanel`.

---

## User Stories

### Unified operational data (P1.8-2)

1. As a **developer**, I want `unified_operational_data_model` mock JSON per shop profile (NEW_SHOP, MID_LARGE_SHOP), so that the pipeline has one input envelope for P2 loader swap.
2. As a **developer**, I want fixtures covering shop metadata, probation, ads, product, inventory, and returns data sets, so that all six workflows have signal coverage.
3. As a **developer**, I want a datum→workflow traceability map with automated tests, so that no orphan data enters the system.
4. As a **QA engineer**, I want schema validation tests on all operational fixtures, so that contract drift is caught in CI.
5. As a **product owner**, I want demo personas mappable to unified model fixtures, so that PersonaSwitcher still drives predictable demos.

### Shop profile classification (P1.8-1)

6. As a **seller**, I want Juli to classify my shop as NEW_SHOP or MID_LARGE_SHOP from operational signals, so that recommendations match my lifecycle stage.
7. As a **seller on probation**, I want only new-shop workflows recommended (NPL, Minimize Violations), so that I am not overwhelmed with growth or loss-prevention tasks I cannot act on.
8. As a **graduated seller**, I want growth and loss-prevention workflows recommended, not probation workflows, so that guidance matches my maturity.
9. As a **developer**, I want `classifyShopProfile()` as a pure function with boundary fixture tests, so that classification is testable without UI.
10. As a **developer**, I want a validated workflow catalog map keyed by profile, so that ranking never surfaces out-of-catalog workflows.
11. As a **developer**, I want operations classification to **extend** (not replace) demo persona routing (`new|leakage|growth`), so that existing P1 demos keep working during migration.

### Health Check subsystem (P1.8-3)

12. As a **seller**, I want a Shop Health hero showing key indicators (probation progress, SPS, AHR, ROAS, inventory, refund spike, scaling opportunity), so that I understand overall shop status at a glance.
13. As a **seller**, I want each health metric tied to the workflow it informs, so that numbers feel actionable not decorative.
14. As a **developer**, I want `computeHealthCheckResults(unifiedModel)` as a pure function, so that health logic is unit-testable.
15. As a **QA engineer**, I want one unit test per health indicator with fixture inputs, so that each signal's computation is regression-protected.
16. As a **compliance reviewer**, I want health fixtures to use masked identifiers only, so that PII rules from P1.7 carry forward.

### Workflow recommendation & ranking (P1.8-4)

17. As a **seller**, I want ranked workflow recommendations (Clarity Cards) with priority, expected impact, and confidence, so that I know what to tackle first.
18. As a **seller**, I want preconditions surfaced on each recommendation (met / unmet), so that I understand why a workflow is or is not actionable.
19. As a **NEW_SHOP seller**, I want recommendations ranked by probation timeline urgency, so that graduation-critical tasks appear first.
20. As a **MID_LARGE_SHOP seller**, I want recommendations ranked by expected revenue impact and urgency, so that high-value actions surface first.
21. As a **product owner**, I want an impact-threshold filter for MID_LARGE_SHOP once Product sets the numeric value; until then mock may rank all eligible workflows.
22. As a **developer**, I want `rankWorkflowRecommendations(profile, health)` returning the `workflow_recommendations` envelope, so that UI consumes a stable contract.
23. As a **developer**, I want `useOperationsPipeline` hook orchestrating load → classify → health → rank, so that UI has one integration point.
24. As a **QA engineer**, I want tests asserting recommendations never reference workflows outside the validated catalog, so that traceability is enforced in CI.

### Rules-only reasoning panel (P1.8-5)

25. As a **seller**, I want to expand each recommendation to see **Why** (triggering health signals), **Expected Impact** (quantified), and **Next Steps**, so that I trust recommendations before approving.
26. As a **seller**, I want reasoning copy in Vietnamese with VND formatting, so that explanations feel native.
27. As a **product owner**, I want all reasoning marked `copy_source: rules`, so that P1.8 does not imply LLM inference.
28. As a **developer**, I want deterministic copy templates keyed by workflow_id and health signals, so that P2 Ollama can swap the copy layer without changing UI structure.
29. As a **QA engineer**, I want tests that reasoning text references only signals present in health results, so that hallucinated explanations cannot ship.

### Unified approval gate & execution routing (P1.8-6)

30. As a **seller**, I want to approve all recommendations, approve selectively, or reject with reason, so that I control what Juli executes.
31. As a **seller**, I want approving NPL to open the listing workflow modal (P1.6), so that executable journeys continue seamlessly.
32. As a **seller**, I want approving Refund Spike Detection to open the leakage workflow modal (P1.7) for the matching task type, so that loss-prevention actions are guided.
33. As a **seller**, I want approving deferred workflows (Violations, Stockout, Budget Optimization, Product Scaling) to show a clear no-op toast, so that I am not misled into thinking TikTok was updated.
34. As a **seller**, I want reject-with-reason on orchestration recommendations using the same reason codes as task dismiss, so that feedback is consistent.
35. As a **developer**, I want approval routing to reuse `useTaskExecutor` and existing modal panels, so that P1.6/P1.7 investment is preserved.
36. As a **QA engineer**, I want E2E tests for both profiles through approve → executable modal → complete, so that the spine is regression-protected.

### Outcome tracking (P1.8-7)

37. As a **seller**, I want per-workflow outcome metrics after execution (success criteria from ADR-026 Appendix B), so that I see whether actions worked.
38. As a **seller**, I want cadence tabs (real-time / daily / weekly / monthly) for outcome views, so that I can track progress at the right granularity.
39. As a **developer**, I want `workflow_outcome_metrics` mock envelopes per workflow_id, so that P2 can swap live metrics without UI rewrite.
40. As a **product owner**, I want outcome views reachable from the operations home after approval/execution, so that the pipeline closes the loop.

### Operations pipeline home (cross-cutting, P1.8-5…7 UI)

41. As a **seller**, I want the seller home to show Shop Health hero + ranked Clarity Cards instead of jumping straight into one copilot panel, so that operations feel unified.
42. As a **seller**, I want existing copilot panels available as execution destinations after approval, so that deep workflow UX is preserved.
43. As a **developer**, I want new UI under `components/workflows/operations/`, so that orchestration surfaces are modular.
44. As a **QA engineer**, I want integration tests loading mock persona → full envelope chain via `useOperationsPipeline`, so that pipeline logic is verified without brittle UI selectors alone.

### Traceability & governance (cross-cutting)

45. As a **product owner**, I want automated traceability tests (datum → workflow, indicator → workflow, recommendation → catalog), so that ADR-026 constraints are CI-enforced.
46. As a **developer**, I want stable `workflow_id` strings matching ADR-026 Appendix A, so that P2 executor mapping is unambiguous.
47. As a **analytics owner**, I want pipeline events (classification, reasoning expand, approve/reject/selective), so that Phase 1.8 metrics in EXECUTION.md are measurable.

### Accessibility & locale (cross-cutting)

48. As a **seller using keyboard**, I want approval gate and Clarity Cards focusable with visible focus rings, so that orchestration is accessible.
49. As a **seller**, I want all user-visible strings in Vietnamese with proper diacritics, so that locale consistency matches prior phases.

---

## Implementation Decisions

### Modules to build/modify (by responsibility)

| Module | Slice | Responsibility | Public interface |
|--------|-------|----------------|------------------|
| **Operational fixtures** | P1.8-2 | Mock `unified_operational_data_model` + traceability map | Loaders + schema validators |
| **Classification** | P1.8-1 | `classifyShopProfile()` + profile→workflow catalog | Pure functions + catalog constant |
| **Health check** | P1.8-3 | `computeHealthCheckResults()` | Pure function → `health_check_results` |
| **Ranking** | P1.8-4 | `rankWorkflowRecommendations()` | Pure function → `workflow_recommendations` |
| **Pipeline hook** | P1.8-4 | `useOperationsPipeline` | React hook: load → classify → health → rank |
| **Reasoning templates** | P1.8-5 | Rules-only Why / Impact / Next Steps | Template functions keyed by workflow + signals |
| **Operations shell UI** | P1.8-5…7 | Health hero, Clarity Cards, reasoning expansion, approval gate, outcome views | React components under `workflows/operations/` |
| **Seller home refactor** | P1.8-6 | `SellerHomeShell` → operations pipeline home | Embeds P1.6/P1.7 panels on route/approve |
| **Approval routing** | P1.8-6 | Map approved workflow_id → listing / leakage / no-op | Extends executor integration |

### Architectural decisions

- **ADR-026 is authoritative** for profiles, catalog, traceability, and routing rules.
- **Extend, don't replace** `seller-stage-router` / `resolveSellerWorkflow` — demo personas (`new|leakage|growth`) remain for backward compatibility; operations classification uses separate rules (probation vs graduated).
- **Stable envelopes** for P2 swap: `unified_operational_data_model`, `health_check_results`, `workflow_recommendations`, `reasoning_summary`, `approved_workflows`, `workflow_outcome_metrics`.
- **Executable routing only:** `npl` → `ListingWorkflowPanel`; `refund_spike_detection` → `LeakageWorkflowPanel` (by mapped task type); all others → no-op toast.
- **Refund Spike sub-journeys:** one validated workflow, four P1.7 task types (`return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy`).
- **Impact threshold:** Product lead sets numeric filter before P1.8-4 filter ships; mock ranks all eligible workflows until recorded in EXECUTION.md.
- **Design tokens:** Build operations UI on ADR-027 tokens when #174 merges; coordinate landing order (tokens early preferred).
- **No new backend:** Mock JSON only; no TikTok API, Postgres, ML, Ollama.

### Schema & API contracts

- New TypeScript schemas under `web/src/lib/mock-data/operations/` and `web/src/lib/operations/`.
- No HTTP API changes in P1.8.

### Integration points

- **PersonaSwitcher** → loads unified operational fixture for selected demo persona.
- **`useTaskExecutor`** → approval gate routes into existing listing/leakage executors.
- **`TaskDismissModal`** → reject-with-reason on orchestration recommendations reuses dismiss reason codes.
- **P1.8-8 (#174)** → Clarity Cards and health hero consume token utilities when available.

### Assumptions

- P1.7 exit gate passes (four leakage types E2E, global skip-with-reason) before P1.8-6 routing work.
- Demo personas map to one of two operational profiles via fixtures (not live shop data).
- Product lead impact threshold may remain TBD during P1.8-4 development; filter is feature-flagged or skipped until set.
- P1.8-8 can land in parallel if token utilities merge before operations UI polish.

---

## Testing Decisions

### What makes a good test

- **Pure logic first:** unit tests for classification, health indicators, ranking rules, reasoning template selection — one behavior per test, minimal fixtures.
- **Traceability as CI gate:** automated tests walk datum map, health→workflow map, recommendation→catalog.
- **Integration:** mock persona → `useOperationsPipeline` → full envelope chain.
- **E2E UI:** both profiles through approve → executable modal (where applicable) → outcome view.
- Match prior art: P1.6 state machine tests, P1.7 `canAdvance` / happy-path per task type, `test_task_executor_issue_167`.

### Modules to test

| Module | Test style |
|--------|------------|
| Fixtures + traceability | Schema validation + map completeness |
| `classifyShopProfile` | Unit: boundary fixtures NEW_SHOP vs MID_LARGE_SHOP |
| `computeHealthCheckResults` | Unit: one test per indicator |
| `rankWorkflowRecommendations` | Unit: ranking order, catalog guard, profile gating |
| `useOperationsPipeline` | Integration: persona → envelope chain |
| Approval routing | Integration/E2E: NPL → listing modal; Refund Spike → leakage modal; deferred → no-op |
| Outcome views | Component: cadence tabs render mock metrics |
| Reasoning | Unit: templates reference only present health signals |

---

## Out of Scope

- **P1.8-8** design-system token migration — separate PRD [#174](https://github.com/thienphung00/Juli-AI/issues/174).
- Standalone executors for Minimize Violations, Stockout Prevention, Budget Optimization, Product Scaling (P2-12…P2-15).
- Routing growth approvals into `GrowthCopilotPanel`.
- TikTok API, Postgres, ML inference, Ollama copy layer (P2).
- New workflows or shop profiles beyond ADR-026 catalog.
- iOS parity, nav redesign, seller-OS retired routes.

---

## Further Notes

### Risks

- **SellerHomeShell refactor** is the largest UX change — mitigate with feature flag or incremental embed of operations home behind persona.
- **Parallel P1.8-8 work** — if orchestration UI ships before tokens, expect visual rework.
- **Threshold TBD** — document in EXECUTION.md when Product sets MID_LARGE_SHOP impact filter.

### Rollout (recommended layer order)

1. **Layer 0:** P1.8-2 fixtures + P1.8-1 classification (+ P1.8-8 tokens in parallel via #174).
2. **Layer 1:** P1.8-3 health + P1.8-4 ranking + `useOperationsPipeline` (TDD).
3. **Layer 2:** Operations shell UI — health hero, Clarity Cards, P1.8-5 reasoning, P1.8-6 approval + routing, P1.8-7 outcomes.
4. **Layer 3:** Integration E2E both profiles; EXECUTION.md + map.md updates.

### Observability

- Pipeline completion rate, classification distribution, approve/reject/selective rates + reject reasons, reasoning-expansion clicks (extend existing UX instrumentation patterns).

### Follow-ups

- Product lead: impact threshold numeric value; operations-system UX sign-off (exit gate).
- P2-11: swap mock loaders for live operational data pipeline.

---

## Assumptions (for issue filing)

- P1.7 engineering exit gate verified; product sign-off pending.
- Validated catalog fixed at six workflows per ADR-026; no expansion without ADR amendment.
- Vietnamese copy, VND formatters, masked IDs carry forward from P1/P1.7 conventions.
