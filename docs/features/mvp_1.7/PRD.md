# PRD: MVP 1.7 — Phase 1.7 Revenue Leakage Executable Workflow

> **Phase:** 1.7 (Weeks 10–11) · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/system-design.md`](../../system-design.md) · **ADR:** [ADR-025](../../decisions/025-revenue-leakage-workflow-scope.md)
>
> **Exit gate:** All four leakage task types completable E2E through success screen; evidence step enforces masked IDs (no PII); global skip-with-reason on dismiss across all workflows; Product lead confirms operational UX resonates.

---

## Problem Statement

Phase 1 shipped Revenue Leakage as an **alert feed** (P1-3): ranked task cards, an evidence drawer, and approve/dismiss via a no-op executor. Sellers can see that return rates spiked or refunds clustered, but approving a task only records intent — nothing guides them through reviewing evidence, understanding root cause, choosing a recommended action, or executing a fix.

Phase 1.6 proved the **executable workflow pattern** for New Seller Copilot (`list_products` → modal stepper → mock execute). Revenue Leakage needs the same operational UX before Phase 2 live APIs: sellers must walk through evidence → root-cause analysis → recommended action → guided mock execution → success confirmation inside the copilot shell, not a separate route maze.

Today the leakage persona includes `affiliate_fraud` and `policy_update` task types that conflict with ADR-011 ML scope and the four-journey product spec. Dismiss lacks structured reasons, limiting UX instrumentation quality across all three copilot workflows.

Phase 1.7 must deliver the **second executable** copilot workflow — four leakage task types, mock fixtures aligned to canonical entities, modal stepper mirroring `ListingWorkflowPanel`, and global skip-with-reason on dismiss. No TikTok API, Postgres, Ollama, or ML inference.

---

## Solution

Extend Revenue Leakage Copilot so approving any of four leakage task types launches a modal workflow (`LeakageWorkflowPanel`) that walks sellers through:

1. **Detail** — task summary, impact estimate, benchmarks
2. **Evidence** — orders, returns, timeline events from typed fixtures (masked buyer IDs only)
3. **Root cause** — rules-only classification and possible causes
4. **Recommended action** — action type, checklist, Vietnamese copy
5. **Execution** — mock stepper per task type (listing update draft, investigation package, monitoring watchlist, shop settings)
6. **Success** — completion headline and recovered-impact metrics

Replace `affiliate_fraud` with `buyer_cancellation_cluster`; rename `policy_update` → `return_window_policy`. Add cancelled-order mock rows for Journey 2 evidence. Dismiss on **all workflows** requires a reason (`false_positive` | `already_handled` | `not_relevant` | `other`) plus optional note.

Evidence drawer content migrates into the workflow evidence step; the drawer may remain as a deep-link entry from task cards. Live TikTok execution is deferred to P2-9 (approval queue) and P2-10 (live executors).

---

## User Stories

### Copilot integration & task launch (P1.7-4)

1. As a **seller**, I want approving a leakage task to open the leakage workflow modal immediately, so that I continue the journey I just committed to.
2. As a **seller**, I want the workflow to feel like a continuation of the alert card I approved, so that the copilot context stays coherent.
3. As a **product owner**, I want only the four leakage task types (`return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy`) to trigger the executable workflow in P1.7, so that scope stays bounded.
4. As a **QA engineer**, I want an integration test that approves each task type and asserts `LeakageWorkflowPanel` mounts, so that E2E entry points are regression-protected.
5. As a **seller**, I want to close the modal and return to the copilot home without corrupting session state, so that I can resume later.
6. As a **developer**, I want the workflow launched from `useTaskExecutor` with a clear extension point for P2 real execution, so that Phase 2 does not require rewiring the entry point.

### Global skip-with-reason (P1.7-4)

7. As a **seller**, I want to dismiss any copilot task only after selecting a reason, so that my feedback is captured meaningfully.
8. As a **seller**, I want skip reasons to be consistent across New Seller, Leakage, and Growth workflows, so that dismiss UX is predictable.
9. As a **seller**, I want to add an optional note when dismissing with reason `other`, so that I can explain edge cases.
10. As a **product owner**, I want dismiss reason events in UX instrumentation, so that false-positive rates are measurable.
11. As a **QA engineer**, I want tests that dismiss without a reason is blocked and dismiss with each reason succeeds, so that the global executor contract is enforced.

### Leakage workflow state machine (P1.7-2)

12. As a **seller**, I want to see my current step in the leakage workflow (detail → evidence → root cause → action → execute → success), so that I know how much is left.
13. As a **seller**, I want to navigate back to a previous step without losing reviewed evidence within the session, so that I can reconsider.
14. As a **seller**, I want session resume after page refresh to restore in-progress workflow state, so that I do not restart from scratch.
15. As a **developer**, I want `canAdvance` guards on each step (e.g., evidence PII check passed), so that invalid progression is impossible.
16. As a **QA engineer**, I want unit tests for step transitions and `canAdvance` per step, so that the state machine is auditable.
17. As a **product owner**, I want step-transition analytics capturable via existing UX instrumentation, so that drop-off points are visible.

### Leakage workflow fixtures (P1.7-1)

18. As a **developer**, I want typed mock fixtures for `LeakageWorkflowTask` matching `canonical-entities.md` § Leakage workflow entities, so that UI and state machine share one schema contract.
19. As a **developer**, I want one complete fixture per task type with evidence bundles, root cause, recommended action, execution plan, and success payload, so that all four journeys are demoable.
20. As a **developer**, I want fixture loaders with stable IDs for golden tests, so that integration tests do not flake.
21. As a **developer**, I want `leakage-persona.ts` task types aligned (`buyer_cancellation_cluster`, `return_window_policy`), with `affiliate_fraud` removed, so that persona cards match workflow fixtures.
22. As a **developer**, I want cancelled-order mock rows in the leakage persona for buyer-cancellation evidence, so that Journey 2 has realistic data.
23. As a **compliance reviewer**, I want all evidence bundles to use masked `buyer_id` (`buyer_***`) only, so that Forbidden #17 is respected.
24. As a **ML engineer** *(indirect)*, I want optional `return_type` on 1–2 `MockReturn` rows as a P2 preview stretch, so that item-swap UI can be exercised without inference.
25. As a **QA engineer**, I want schema validation tests on all leakage workflow fixtures, so that contract drift is caught in CI.

### Detail step (P1.7-3)

26. As a **seller**, I want the detail step to show task title, severity, estimated GMV impact, and summary copy in Vietnamese, so that I understand why this alert matters.
27. As a **seller**, I want benchmark comparisons (e.g., return rate vs category median) when present in fixtures, so that I have context for the spike.
28. As a **seller**, I want affected product IDs linked to product titles from persona orders, so that I know which SKUs are involved.

### Evidence step (P1.7-3)

29. As a **seller**, I want the evidence step to show orders, returns, and timeline events from the fixture bundle, so that I can verify the alert before acting.
30. As a **seller**, I want evidence displayed with masked buyer IDs only, so that I trust Juli respects privacy policy.
31. As a **developer**, I want `assertEvidenceHasNoRawPii` invoked on every evidence render, so that raw PII cannot slip into the UI.
32. As a **seller**, I want to mark evidence as reviewed before advancing, so that I consciously acknowledge what I saw.
33. As a **QA engineer**, I want a test that forbidden PII keys in fixtures throw or fail the guard, so that the PII contract is enforced.

### Root cause step (P1.7-3)

34. As a **seller**, I want root-cause classification (seller optimization, buyer risk, shop config, undetermined) with confidence and summary, so that I understand the diagnosis.
35. As a **seller**, I want a list of possible causes from rules-only copy, so that I can validate Juli’s reasoning.
36. As a **product owner**, I want `copy_source: rules` on all root-cause copy in P1.7, so that we do not imply ML inference.

### Recommended action step (P1.7-3)

37. As a **seller**, I want the recommended action to show action type, summary, and a checklist, so that I know what will happen on execute.
38. As a **seller**, I want action types mapped per task type (listing update, investigation package, monitoring, shop settings), so that each journey feels operationally distinct.

### Mock execution step (P1.7-3)

39. As a **seller**, I want `return_spike` execution to simulate a listing update draft → apply, so that I practice fixing size/description issues.
40. As a **seller**, I want `buyer_cancellation_cluster` execution to simulate an investigation report → support case draft, so that I practice escalating buyer-risk patterns.
41. As a **seller**, I want `refund_cluster` execution to simulate a refund report → watchlist, so that I practice monitoring concentrated refunds.
42. As a **seller**, I want `return_window_policy` execution to simulate settings review → apply config, so that I practice tightening return windows.
43. As a **seller**, I want a stepper UI showing mock execution sub-steps with progress, so that long-running P2 operations feel familiar.
44. As a **seller**, I want deterministic mock durations from fixture `mock_duration_ms`, so that demos are reproducible.

### Success step & completion (P1.7-3, P1.7-4)

45. As a **seller**, I want a success screen with headline and recovered-impact metrics after mock execute completes, so that I feel closure on the task.
46. As a **seller**, I want the completed task removed from the active queue after success, so that my copilot home reflects progress.
47. As a **QA engineer**, I want happy-path integration tests for all four task types through success, so that the exit gate is verifiable.

### Evidence drawer coexistence (P1.7-3)

48. As a **seller**, I want the existing “Xem bằng chứng” drawer to remain as a quick preview entry, so that I can peek at evidence before approving.
49. As a **developer**, I want drawer and workflow evidence step to share the same resolver and PII guard, so that behavior is consistent.

### Cross-cutting

50. As a **seller**, I want Vietnamese labels and helper text throughout the workflow, so that the UI matches the rest of the copilot.
51. As a **seller**, I want the workflow to work in UI-only mode without backend calls, so that demos run offline.
52. As a **developer**, I want `map.md` rows updated when leakage workflow modules land, so that architecture docs stay current.
53. As a **security reviewer**, I want no raw buyer PII, secrets, or scrape URLs in fixtures, so that P1.7 complies with data-source policy.
54. As a **product owner**, I want EXECUTION.md P1.7-1…P1.7-5 slices traceable to implementation issues, so that governance stays intact.
55. As a **developer**, I want `LeakageWorkflowTask` envelope stable for P2 inference swap, so that UI step graph does not change in Phase 2.

---

## Implementation Decisions

### Modules to build/modify (by responsibility)

| Module | Responsibility | Public interface |
|--------|----------------|------------------|
| **Leakage workflow fixtures** | Seed `LeakageWorkflowTask` JSON per type; typed loaders; persona alignment | `loadLeakageWorkflowTask(taskId)`, `loadLeakageFixtures()` |
| **Leakage workflow state machine** | Step graph, session state, navigation guards, workflow status enum | `useLeakageWorkflow()` hook + `state-machine.ts` |
| **Leakage workflow UI** | Modal panel, step renderers per task type, execution stepper | `LeakageWorkflowPanel` + step components |
| **Task executor extension** | Leakage approve opens workflow; global skip-with-reason on dismiss | Extend `useTaskExecutor`, `TaskCard` dismiss flow |
| **Evidence resolver** (existing) | Resolve evidence refs; PII guard | Reuse `resolveEvidence`, `assertEvidenceHasNoRawPii` |
| **UX instrumentation** (existing) | Step events, dismiss reasons, workflow completion | Extend `track.ts` event types |

### Architectural decisions

- **ADR-025 is authoritative:** P1.7 = mock fixtures + rules-only copy; no cloud LLM, Postgres, TikTok API, or ML inference.
- **Entry point:** Approved leakage tasks only — modal inside `LeakageCopilotPanel`, not new `/leakage/*` routes.
- **Task types:** `return_spike`, `buyer_cancellation_cluster`, `refund_cluster`, `return_window_policy` — not `affiliate_fraud` (P2 policy alerts).
- **Persona migration:** Replace `task_leak_002` (`affiliate_fraud`) with `buyer_cancellation_cluster`; rename `policy_update` → `return_window_policy`; add cancelled-order rows for evidence.
- **Global dismiss:** Skip reasons apply to New Seller, Leakage, and Growth — shared dismiss modal/component.
- **Persistence:** Session-scoped state in `task-executor/session-store` and workflow-specific session keys; Postgres in P2.
- **Evidence drawer:** Retained as deep-link; workflow evidence step is primary post-approve path.

### Schema & contracts

- Workflow entities conform to [`canonical-entities.md`](../../data-models/canonical-entities.md) § Leakage workflow entities.
- `workflow_status`: `new` → `in_review` → `evidence_reviewed` → `ready_to_execute` → `executing` → `completed` | `skipped`.
- `skip_reason`: `false_positive` | `already_handled` | `not_relevant` | `other`; optional `skip_note`.
- `action_type` on recommended action: `listing_update` | `investigation_package` | `monitoring` | `shop_settings`.
- Mock execution mapping per ADR-025 / system-design §7.

### Integration points

- **Copilot home → leakage workflow:** `LeakageCopilotPanel` / `TaskQueue` → `LeakageWorkflowPanel` on approve.
- **Fixtures → UI:** Each step reads from `LeakageWorkflowTask` fixture for the approved task ID.
- **Executor → session:** Complete sets disposition; skip sets `skipped` + reason on session record.
- **P2 envelope:** Same `LeakageWorkflowTask` shape; loaders swap from fixtures to API.

### Assumptions

- P1.6 listing workflow patterns (`state-machine.ts`, modal portal, session persistence) are shipped on `main` before P1.7 implementation begins.
- P1.5 ML gate remains open but does not block P1.7 (noted in EXECUTION.md).
- `return_type` on 1–2 `MockReturn` rows is optional stretch in P1.7-1 — not exit-gate blocking.
- Vietnamese copy follows existing copilot tone; no Ollama localization in P1.7.
- Growth Copilot receives global skip-with-reason UI but no executable workflow in P1.7.

---

## Testing Decisions

### What makes a good test

- Test **public behavior** through UI integration tests (`web/src/__tests__/`) and state-machine unit tests — not implementation details.
- One behavior per `describe` block; name scenarios explicitly (return_spike happy path, PII guard, dismiss reason required).
- Use stable fixture IDs from P1.7-1; no random data in assertions.
- Match existing patterns: `test_listing_workflow_ui.test.tsx`, `test_revenue_leakage_ui.test.tsx`, `test_task_card_executor.test.tsx`.

### Modules to test

| Module | Test style |
|--------|------------|
| Fixtures | Schema validation + loader returns expected task types/IDs |
| State machine | Unit tests for transitions, `canAdvance`, session resume |
| LeakageWorkflowPanel | Integration tests: approve → each type → success |
| PII guard | Unit/integration: `assertEvidenceHasNoRawPii` on evidence step |
| Global dismiss | Integration: reason required; all four reason enums work |
| UX instrumentation | Assert step and dismiss events fire with expected payloads |

### Prior art

- `web/src/__tests__/test_listing_workflow_ui.test.tsx` — modal workflow E2E
- `web/src/__tests__/test_revenue_leakage_ui.test.tsx` — leakage copilot panel
- `web/src/__tests__/test_task_card_executor.test.tsx` — approve/dismiss executor
- `web/src/lib/workflows/leakage/resolve-evidence.ts` — evidence + PII guard

---

## Out of Scope

- TikTok API calls (Orders, Products, support case submit) — Phase 2 (P2-9, P2-10)
- Postgres persistence / copilot API routes — Phase 2
- ML inference for anomaly detection — Phase 1.5 / Phase 2
- Ollama copy rewrite — Phase 2
- `affiliate_fraud` executable journey — replaced; affiliate policy alerts in P2-4
- New App Router routes (`/leakage/*`) — modal only per ADR-025
- Fifth leakage task type
- Seller Center scraping, buyer PII, realtime unofficial streams — permanently forbidden
- iOS parity, nav redesign, web analytics dashboard
- Changes to Growth Copilot executable workflow (none in P1.7)

---

## Further Notes

### Risks

- **Global dismiss scope:** Touching all three workflows increases regression surface — test listing and growth dismiss paths.
- **Persona migration:** Removing `affiliate_fraud` may break existing tests referencing `task_leak_002` — update in P1.7-1.
- **Evidence drawer duplication:** Keep single resolver to avoid divergent evidence rendering.

### Rollout

1. Ship fixtures + persona alignment first (P1.7-1) — unblocks parallel state machine and UI work.
2. State machine (P1.7-2) before full panel (P1.7-3) so step graph is testable in isolation.
3. Executor integration (P1.7-4) wires approve/dismiss after panel steps exist.
4. Integration tests + instrumentation (P1.7-5) complete the exit gate.

### Observability

- Extend UX instrumentation: `leakage_workflow_started`, `leakage_step_completed`, `leakage_workflow_completed`, `task_dismissed_with_reason`.
- Log `copy_source: rules` for all root-cause and action copy (no LLM in P1.7).

### Follow-ups (Phase 2)

- P2-9 leakage approval queue before live mutations
- P2-10 live executors (listing update, support case draft, shop settings)
- Swap fixture loaders → inference API envelope; Ollama rewrites copy only
- Affiliate/policy signals as separate alert tasks (P2-4)
