# PRD: MVP 1.6 — Phase 1.6 New Seller Listing Workflow

> **Phase:** 1.6 (Weeks 9–10) · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/system-design.md`](../../system-design.md) · **ADR:** [ADR-020](../../decisions/020-new-seller-listing-workflow-scope.md)
>
> **Exit gate:** E2E listing flow complete — recommend (`list_products`) → approve → Path A **or** Path B → fill forms → execute (CSV export minimum); both paths exercised; deterministic readiness/compliance; shop-progress bar updates after execute.

---

## Problem Statement

Phase 1 shipped a New Seller Copilot with a generic `list_products` mock task (P1-2) and a no-op executor (P1-5): sellers can approve the recommendation, but nothing happens afterward. The copilot recommends "add more products" without guiding sellers through *how* to list — no distributor lookup, no opportunity discovery, no draft generation, and no export for manual TikTok Seller Center upload.

New sellers on TikTok Shop must reach **Standard status**, which requires **10 active listings**. Today Juli-AI surfaces the milestone in mock copy but provides no executable path from recommendation to a publishable product draft. Sellers who lack an existing supplier (Path A: distributor-known) or who want trend-guided discovery (Path B: opportunity → distributor) have no in-product workflow.

Phase 1.6 must deliver the **first executable** New Seller Copilot task — wired through the existing task queue and approval UX — using mock fixtures and rules-only generation. No cloud LLM, no Postgres, no TikTok API. Success is measured by E2E completion rate through the full chain, not checklist-only navigation.

---

## Solution

Extend the New Seller Copilot so that approving the `list_products` task launches a dual-path listing workflow:

- **Path A (distributor-known):** Seller enters product details and selects/confirms a distributor from curated mock catalogs → rules engine produces a `ProductDraft` with compliance checks and readiness score → seller reviews → execute exports CSV/JSON for manual Seller Center upload.
- **Path B (opportunity discovery):** Seller sets profile constraints → browses filtered `Opportunity` cards from mock catalogs → selects distributor → same generation/review/export chain as Path A.

The workflow reuses P1 mock-fixture patterns, canonical workflow entities (`ProductDraft`, `Distributor`, `Opportunity`), and the existing task executor — upgrading `list_products` approval from no-op to workflow launch. A task card widget tracks listing progress toward the 10-listing Standard-status milestone.

---

## User Stories

### Copilot integration & task launch (P1.6-2)

1. As a **new seller**, I want approving the "add products" copilot task to open the listing workflow immediately, so that I do not hunt for a separate checklist page.
2. As a **new seller**, I want the listing workflow to feel like a continuation of the copilot recommendation I just approved, so that the journey feels coherent.
3. As a **product owner**, I want only `list_products` tasks to trigger the executable workflow in P1.6 (other task types remain no-op), so that scope stays bounded.
4. As a **QA engineer**, I want an integration test that approves `list_products` and asserts the listing workflow UI mounts, so that the E2E entry point is regression-protected.
5. As a **seller**, I want to dismiss or abandon the workflow and return to the copilot home without losing my session state confusingly, so that I can resume later.
6. As a **developer**, I want the workflow launched from the existing `useTaskExecutor` hook with a clear extension point for P2 real execution, so that Phase 2 does not require rewiring the entry point.

### Path selection & state machine (P1.6-2)

7. As a **new seller**, I want to choose between "I have a distributor" (Path A) and "Help me find products" (Path B) after approving the task, so that the flow matches my situation.
8. As a **new seller**, I want to see my current step in the workflow (path selection → input/discovery → draft review → export), so that I know how much is left.
9. As a **new seller**, I want to go back to a previous step without losing entered data within the session, so that I can correct mistakes.
10. As a **QA engineer**, I want tests covering Path A and Path B state transitions independently, so that both personas are verifiable.
11. As a **product owner**, I want path selection analytics (A vs B rate) capturable via existing UX instrumentation, so that we learn which persona dominates.
12. As a **seller**, I want Vietnamese labels and helper text throughout the workflow, so that the UI matches the rest of the copilot.

### Path A — distributor-known fast listing (P1.6-2, P1.6-3)

13. As a **new seller with a known supplier**, I want to enter product name, category, price, and optional URL stub, so that Juli can generate a draft without external APIs.
14. As a **new seller**, I want to search or pick a distributor from a curated mock catalog filtered by category, so that I can associate my listing with a supplier.
15. As a **new seller**, I want the form to validate required fields before proceeding, so that I do not reach an empty draft review.
16. As a **new seller**, I want URL stub input to produce deterministic extracted fields (rules-only, no LLM), so that I can test the extraction UX before P2 Ollama.
17. As a **QA engineer**, I want a golden Path A fixture (form input → expected `ProductDraft` fields), so that extraction behavior is auditable.

### Path B — opportunity discovery (P1.6-2, P1.6-1)

18. As a **new seller without a supplier**, I want to set capital budget, preferred category, and dropship preference, so that opportunities are filtered to my constraints.
19. As a **new seller**, I want to browse opportunity cards showing demand, competition, margin, and trend scores from mock data, so that I can pick a product direction.
20. As a **new seller**, I want opportunity filters to be deterministic (same inputs → same card set), so that demos and tests are reproducible.
21. As a **new seller**, I want to select an opportunity and see suggested distributors from the mock catalog, so that I can complete the supplier step.
22. As a **new seller**, I want to confirm distributor selection and proceed to draft generation, so that Path B converges with Path A at draft review.
23. As a **QA engineer**, I want tests for opportunity filtering (capital ceiling, category match, dropship flag), so that Path B discovery logic is covered.

### Mock workflow fixtures (P1.6-1)

24. As a **developer**, I want typed mock fixtures for `ProductDraft`, `Distributor`, and `Opportunity` matching `canonical-entities.md` § Workflow entities, so that UI and rules engine share one schema contract.
25. As a **developer**, I want seed data covering at least 5 distributors across 3 categories and 8 opportunities with varied scores, so that Path A and Path B have realistic cards to display.
26. As a **developer**, I want fixture loaders with stable IDs for golden tests, so that integration tests do not flake on random data.
27. As a **ML engineer** *(indirect)*, I want workflow entity shapes aligned with P2 Postgres design, so that persistence migration does not require schema rework.
28. As a **compliance reviewer**, I want mock `source` enums to exclude forbidden values (Seller Center scrape, marketplace API) in P1.6 fixtures, so that data-source policy is respected in demos.

### Rules-based listing generation (P1.6-3)

29. As a **new seller**, I want Juli to generate listing title, description, bullet points, SEO keywords, and hashtags from my inputs using deterministic rules, so that I get a complete draft without waiting on an LLM.
30. As a **new seller**, I want compliance checks to flag blocked categories, missing required fields, and policy warnings before export, so that I know what would fail on TikTok.
31. As a **new seller**, I want a readiness score (0–100) with suggested improvements, so that I understand draft quality before uploading manually.
32. As a **seller**, I want the same inputs to always produce the same draft and scores, so that the rules engine is auditable and trustworthy.
33. As a **QA engineer**, I want unit tests for compliance edge cases (blocked category, missing price, empty title) each asserting a single public outcome, so that CI output is actionable.
34. As a **QA engineer**, I want unit tests for readiness scoring boundaries (e.g., minimal vs complete listing content), so that score distribution is verifiable.
35. As a **product owner**, I want compliance `blocked` status to prevent export until resolved, so that sellers cannot download invalid drafts.
36. As a **developer**, I want the rules engine behind a small public interface (input context → `ProductDraft`), so that P2 can swap mock extraction for Ollama without UI changes.

### Draft review (P1.6-2, P1.6-3)

37. As a **new seller**, I want to review the generated draft with compliance warnings and readiness score visible, so that I can decide whether to export or go back and edit.
38. As a **new seller**, I want to see blocking issues highlighted separately from warnings, so that I know what must be fixed.
39. As a **new seller**, I want to edit key fields inline before export, so that I can personalize the listing.
40. As a **QA engineer**, I want draft review to reflect live edits updating readiness/compliance on re-validation, so that inline edit behavior is tested.

### CSV/JSON export & execute step (P1.6-4)

41. As a **new seller**, I want to download my approved `ProductDraft` as CSV and JSON, so that I can upload manually to TikTok Seller Center.
42. As a **new seller**, I want the execute step to confirm export success with a clear next-action message (manual upload instructions), so that I know the copilot task is complete.
43. As a **new seller**, I want export blocked when compliance status is `blocked`, so that I cannot download invalid listings.
44. As a **QA engineer**, I want an integration test that completes Path A through export and asserts downloadable artifact shape matches schema, so that the execute step is E2E verifiable.
45. As a **QA engineer**, I want an integration test for Path B through export, so that both paths meet the exit gate.
46. As a **developer**, I want export implemented client-side or via mock module (no TikTok API), so that P1.6 stays within phase constraints.

### Shop progress & task card widget (P1.6-5)

47. As a **new seller**, I want my listing count toward the 10-listing Standard-status goal to update after I execute export, so that I see progress toward the milestone.
48. As a **new seller**, I want a task card widget showing one of four states (NoDistributor / DistributorKnown / DraftGenerated / Published-stub), so that I know where I am in the listing journey.
49. As a **new seller**, I want the progress bar on the copilot home to reflect mock listing count after execute, so that the milestone UI stays honest.
50. As a **product owner**, I want export rate and average readiness score measurable via existing instrumentation hooks, so that P1.6 metrics are captured.
51. As a **QA engineer**, I want a test that execute increments mock listing count and updates widget state, so that progress tracking does not regress.

### Cross-cutting

52. As a **seller**, I want the workflow to work in UI-only mode (`isUiOnly`) without backend calls, so that demos run offline.
53. As a **developer**, I want MODULE.md or map.md rows updated when listing modules land, so that architecture docs stay current.
54. As a **security reviewer**, I want no PII, secrets, or external scrape URLs in fixtures or export artifacts, so that P1.6 complies with data-source policy.
55. As a **product owner**, I want EXECUTION.md P1.6-1…P1.6-5 slices traceable to implementation issues, so that governance stays intact.

---

## Implementation Decisions

### Modules to build/modify (by responsibility)

| Module | Responsibility | Public interface |
|--------|----------------|------------------|
| **Listing workflow fixtures** | Seed `ProductDraft`, `Distributor`, `Opportunity` JSON; typed loaders | `loadDistributors()`, `loadOpportunities()`, `loadListingFixtures()` |
| **Listing rules engine** | Form/URL-stub extraction, compliance checks, readiness scoring | `generateProductDraft(context) → ProductDraft` |
| **Listing workflow state machine** | Path A/B steps, session state, navigation guards | `useListingWorkflow()` hook or equivalent reducer |
| **Listing workflow UI** | Path selection, forms, opportunity browser, draft review, export | React components under new-seller listing workflow |
| **Task executor extension** | `list_products` approve launches workflow; other types remain no-op | Extend `useTaskExecutor` / routing |
| **Export service** | CSV/JSON serialization from `ProductDraft` | `exportProductDraft(draft, format)` |
| **Shop progress tracker** | Mock listing count + task card widget states | `updateListingProgress()`, widget state enum |

### Architectural decisions

- **ADR-020 is authoritative:** P1.6 = mock fixtures + rules-only; no cloud LLM, Postgres, or TikTok API.
- **Entry point:** Approved `list_products` task only — not a standalone checklist route (supersedes generic P1-2 list flow for this task type).
- **Path B catalogs:** Hand-curated mock JSON with deterministic filters (capital, category, dropship) — not third-party marketplace APIs.
- **LLM boundary:** Extraction and compliance ranking stay deterministic; Ollama deferred to P2 for copy rewrite only.
- **Persistence:** Session-scoped state in P1.6 (localStorage or in-memory); Postgres `product_drafts` in P2.
- **Executor message:** Update feedback copy for `list_products` from Phase 1 no-op text to workflow-launch confirmation.

### Schema & contracts

- Workflow entities conform to [`canonical-entities.md`](../../data-models/canonical-entities.md) § Workflow entities.
- `ProductDraft.status`: `in_progress | ready_for_export | blocked`.
- `ProductDraft.compliance.status`: `approved | warning | blocked` — export gated on `blocked`.
- `ProductDraft.readiness.overall_score`: integer 0–100, deterministic from field completeness and compliance.

### Integration points

- **Copilot home → listing workflow:** `NewSellerCopilotPanel` / `TaskQueue` → workflow route or modal on `list_products` approve.
- **Fixtures → UI:** Opportunity browser and distributor picker read mock catalogs.
- **Rules engine → draft review:** Generated draft passed to review step; inline edits re-invoke validation.
- **Export → progress:** Successful execute increments mock SKU/listing count on persona profile.

### Assumptions

- P1-5 executor approval UX is shipped or in-flight; P1.6 extends it for `list_products` only.
- Phase 1.5 exit gate (recommend → approve only) passes before P1.6 work begins in production timeline.
- Vietnamese copy for workflow steps follows existing copilot tone; no Ollama localization in P1.6.
- URL stub extraction uses deterministic parsing rules (e.g., hostname → category hint), not real page fetch.

---

## Testing Decisions

### What makes a good test

- Test **public behavior** through UI integration tests (`web/src/__tests__/`) and rules-engine unit tests — not implementation details.
- One behavior per test class/`describe` block; name scenarios explicitly (Path A export, Path B filter, compliance blocked).
- Use stable fixture IDs from P1.6-1; no random data in assertions.
- Match existing patterns: `test_new_seller_copilot.test.tsx`, `test_task_card_executor.test.tsx`.

### Modules to test

| Module | Test style |
|--------|------------|
| Fixtures | Schema validation + loader returns expected counts/IDs |
| Rules engine | Unit tests per compliance rule and readiness boundary |
| State machine | Unit tests for transitions and guards |
| E2E UI | Integration tests: approve → Path A → export; approve → Path B → export |
| Export | Unit test: draft → CSV/JSON shape matches schema |
| Progress tracker | Integration test: execute updates count and widget state |

### Prior art

- `web/src/__tests__/test_new_seller_copilot.test.tsx` — copilot panel integration
- `web/src/__tests__/test_task_card_executor.test.tsx` — approve/dismiss no-op executor
- `tests/unit/test_scoring.py` — one-behavior-per-test pattern (Python; listing rules are TypeScript)

---

## Out of Scope

- Cloud LLM (Claude or other) for extraction or copy — Phase 2 Ollama
- Postgres persistence / copilot API routes — Phase 2
- TikTok Products API publish — Phase 2 (P2-8)
- Listing approval queue — Phase 2 (P2-7)
- Third-party marketplace supplier APIs — Phase 3+
- Seller Center scraping or live URL fetching — permanently forbidden
- Real PDF/URL document parsing — P2 Ollama
- iOS parity, nav redesign, web analytics dashboard
- Changes to Revenue Leakage or Growth Copilot workflows

---

## Further Notes

### Risks

- **Scope creep into P2:** Guard all interfaces so persistence and API publish are additive slices, not rewrites.
- **P1-5 dependency:** If executor UX changes, coordinate `list_products` launch hook.
- **URL stub quality:** P1.6 cannot validate real extraction quality; set seller expectations in copy.

### Rollout

1. Ship fixtures first (P1.6-1) — unblocks parallel UI and rules work.
2. Wire copilot entry point early in P1.6-2 so E2E demos are possible before export lands.
3. Export + progress (P1.6-4, P1.6-5) complete the exit gate.

### Observability

- Extend existing UX instrumentation: `list_products` workflow_started, path_selected, export_completed, readiness_score bucket.
- Log `copy_source: rules` for all generated listing content (no LLM in P1.6).

### Follow-ups (Phase 2)

- P2-7 approval queue before publish
- P2-8 Products API publish from approved `ProductDraft`
- Migrate fixtures → Postgres; Ollama copy layer on structured signals only
