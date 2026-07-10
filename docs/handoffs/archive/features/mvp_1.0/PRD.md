# PRD: MVP 1.0 — Phase 1 UI + Mock Data

> **Phase:** 1 (Weeks 1–6) · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/architecture/system-design.md`](../../architecture/system-design.md)
>
> **Exit gate:** Mockup UI live for all three workflows; 100 test sellers exercised the flows; engagement threshold met (set by Product lead).

---

## Problem Statement

TikTok Shop sellers in Vietnam lose money in predictable ways: new sellers stall before their first profitable sale, established shops bleed GMV through returns, refunds, and affiliate fraud, and growth-stage sellers waste ad budget on underperforming campaigns. Juli-AI's north star is **seller money** — help sellers make and keep more money through three agentic workflows.

Today the product surface still reflects a superseded creator-matching direction. Sellers cannot yet experience the three rescoped workflows (New Seller Copilot, Revenue Leakage Detection, Growth Copilot) end-to-end. Without a realistic, mock-data-driven UI, the team cannot validate whether these workflows resonate with real sellers before investing in ML training (Phase 1.5) or live TikTok API integration (Phase 2).

Phase 1 must ship a complete mockup experience: sellers see personalized tasks, understand why each recommendation matters, and can approve or dismiss actions — all powered by hardcoded fixtures and rules, with no real API calls and no ML.

---

## Solution

Ship a Vietnamese-language web experience for all three seller-money workflows, populated with realistic mock seller profiles, orders, returns, affiliate signals, and ad performance data. A rules-based seller-stage router determines which workflow a seller sees. Each workflow surfaces ranked tasks with clear justification and a call-to-action. Sellers approve or dismiss tasks through an executor UI that records intent but performs no backend action (no-op). UX instrumentation captures task clicks and approval-flow completions so Product can validate engagement with 100 test sellers.

The experience mirrors the Phase 2 end-to-end shape (data → decision tree → tasks → copy → approval) but substitutes mock JSON for live data and hardcoded copy for the LLM copy layer.

---

## User Stories

### Onboarding & routing

1. As a **new TikTok Shop seller**, I want to land in an onboarding flow that shows me the next steps to reach my first profitable sale, so that I know exactly what to do instead of guessing.
2. As a **seller logging in for the first time**, I want the app to recognize that I am in the "new seller" stage based on my shop profile (low order count, recent shop age), so that I see the New Seller Copilot instead of growth or leakage workflows.
3. As a **growth-stage seller** with healthy order volume and ad spend, I want to be routed to the Growth Copilot, so that I see ad performance insights relevant to scaling.
4. As a **seller with elevated return or refund rates**, I want to be routed to Revenue Leakage Detection, so that I can address money leaving my shop before it compounds.
5. As a **seller**, I want to switch between mock seller profiles (or have a demo profile assigned), so that I can experience each workflow during the 100-seller UX test.
6. As a **seller**, I want all UI text in Vietnamese with proper diacritics and VND currency formatting, so that the product feels native to my market.
7. As a **seller on mobile**, I want single-thumb-friendly layouts for task cards and approval actions, so that I can review recommendations on my phone.

### New Seller Copilot (P1-2)

8. As a **new seller**, I want to see a guided checklist of tasks (e.g., complete shop setup, list first product, enable affiliate, run first ad), so that I progress toward first profitable sales in order.
9. As a **new seller**, I want each task to explain *why* it matters (e.g., "Shops with 3+ SKUs convert 2× better"), so that I trust the recommendation.
10. As a **new seller**, I want to see my progress toward "first sale" with a visible milestone, so that I stay motivated.
11. As a **new seller**, I want to dismiss a task I have already completed or disagree with, so that my task list stays relevant.
12. As a **new seller**, I want to approve a recommended task, so that I signal intent even when no real action executes yet.
13. As a **new seller**, I want empty or completed states handled gracefully (no broken layouts), so that the UI always feels polished.
14. As a **new seller**, I want mock data to reflect realistic Vietnamese shop names, product titles, and price points, so that the demo feels credible.

### Revenue Leakage Detection (P1-3)

15. As a **seller losing money to returns**, I want to see surfaced anomalies (return spikes, refund clusters, suspicious affiliate cancellation patterns), so that I know where GMV is leaking.
16. As a **seller**, I want each leakage alert to show severity (e.g., high / medium / low) and estimated GMV impact in VND, so that I can prioritize fixes.
17. As a **seller**, I want a recommended fix for each leakage signal (e.g., update return policy, block affiliate, adjust product listing), so that I know what action to take.
18. As a **seller**, I want to drill into a leakage item to see supporting mock evidence (order IDs, return reasons, affiliate IDs — masked, no buyer PII), so that I believe the signal.
19. As a **seller**, I want to approve a recommended fix, so that I record my decision for UX testing.
20. As a **seller**, I want to dismiss a false positive, so that the product can later learn from dismiss patterns (instrumented in Phase 1, acted on in Phase 2).
21. As a **seller with no leakage signals**, I want a positive empty state ("No leakage detected this week"), so that I am not alarmed unnecessarily.

### Growth Copilot (P1-4)

22. As a **growth-stage seller**, I want to see ad performance summaries (spend, ROAS, CPC, conversions) from mock data, so that I understand how my campaigns are performing.
23. As a **growth-stage seller**, I want recommendations to scale winning campaigns and cut underperformers, so that I improve ROAS without manual spreadsheet work.
24. As a **growth-stage seller**, I want each ad recommendation to cite the mock metrics behind it (e.g., "ROAS 4.2× over 7 days, 15% above account average"), so that I trust scale/cut suggestions.
25. As a **growth-stage seller**, I want to approve a "scale" or "pause" recommendation, so that I express intent for UX validation.
26. As a **growth-stage seller**, I want to see multiple campaigns ranked by opportunity, so that I focus on the highest-impact change first.
27. As a **growth-stage seller**, I want dismiss actions on ad tasks I disagree with, so that my feed reflects my judgment during testing.

### Executor approval flow — no-op (P1-5)

28. As a **seller**, I want a consistent approve/dismiss interaction across all three workflows, so that the UX is predictable.
29. As a **seller**, I want visual confirmation when I approve or dismiss (toast or inline state change), so that I know my action was recorded.
30. As a **seller**, I want approved tasks to move to a "completed" or "acknowledged" state in the UI, so that I can track what I have already handled.
31. As a **seller**, I want dismissed tasks to leave the active queue (or move to dismissed history), so that my feed does not clutter.
32. As a **product owner**, I want approve/dismiss events to emit analytics events, so that we can measure approval-flow completion rates.
33. As a **seller**, I want to understand that approving a task does not yet trigger real TikTok actions (copy or tooltip in demo mode), so that I am not surprised in Phase 1.

### Rules-based seller-stage detection (P1-6)

34. As a **system**, I want to classify sellers into lifecycle stages (new, leakage-risk, growth) using deterministic rules on mock profile fields (order count, shop age, return rate, ad spend), so that routing is reproducible for UX testing.
35. As a **developer**, I want seller-stage rules documented and unit-testable, so that Phase 1.5 can compare ML classifier output against this baseline.
36. As a **seller**, I want the app to show which workflow I am in (label or breadcrumb), so that I understand why I see specific tasks.
37. As a **QA tester**, I want fixture profiles that hit each stage boundary (threshold edge cases), so that routing can be verified without live data.

### Mock data layer (P1-1)

38. As a **developer**, I want JSON schemas for seller profiles, orders, returns, affiliate events, and ad campaigns, so that fixtures are consistent and validatable.
39. As a **developer**, I want at least three hardcoded seller personas (new, leakage, growth) with realistic Vietnamese data, so that all workflows are demoable without a backend.
40. As a **developer**, I want mock task copy (titles, bodies, CTAs) colocated with fixtures, so that the copy layer is swappable in Phase 2.
41. As a **developer**, I want schemas to forbid buyer PII fields, so that Phase 1 fixtures comply with data-source policy.
42. As a **designer**, I want sample data volumetric enough to stress-test lists and cards (10+ orders, multiple campaigns), so that layouts work at realistic density.

### UX instrumentation (P1-7)

43. As a **product lead**, I want task-click events logged with workflow, task type, and seller persona, so that I can measure engagement per workflow.
44. As a **product lead**, I want approval and dismiss events logged with timestamps, so that I can compute approval-flow completion rates.
45. As a **product lead**, I want session-level aggregates exportable or visible in an analytics sink (existing analytics utility or equivalent), so that the 100-seller test produces measurable data.
46. As a **engineer**, I want analytics calls to fail silently without breaking the UI, so that instrumentation never blocks sellers.
47. As a **product lead**, I want an engagement threshold definition documented (e.g., % of sellers completing ≥1 approval per workflow), so that the Phase 1 exit gate is objective.

### Cross-cutting UX

48. As a **seller**, I want to log in via one-click demo entry, so that I access the mock workflows for review.
49. As a **seller**, I want fast page loads (target ≤2s), so that the mockup feels production-quality.
50. As a **seller**, I want responsive layouts from mobile to desktop, so that I can test on any device.
51. As a **seller returning after dismissing tasks**, I want my dismissals persisted for the session (local state), so that the feed does not reset annoyingly.
52. As a **developer**, I want legacy creator-matching pages retired or redirected without breaking auth, so that sellers only see seller-money workflows.

### Workspace mode (Seller vs Affiliate)

53. As a **user**, I want to choose Seller or Affiliate mode after login, so that the app reflects my role.
54. As a **seller**, I want Seller mode to use a dark theme, so that the seller experience is visually distinct.
55. As an **affiliate**, I want Affiliate mode to use a light theme, so that the affiliate experience is visually distinct.
56. As an **affiliate**, I want every page in Affiliate mode to show a clear "Out of Scope" message (Phase 1), so that I know affiliate workflows are not built yet.
57. As a **seller**, I want all three seller-money workflows available only in Seller mode, so that Phase 1 scope stays focused.
58. As a **user**, I want to switch modes via the existing mode switcher without losing auth, so that I can demo both themes.

---

## Implementation Decisions

### Modules to build or modify (by responsibility)

| Module | Responsibility | Public interface (behavioral) |
|--------|----------------|------------------------------|
| **Mock data layer** | JSON schemas + typed fixtures for seller profiles, orders, returns, affiliate signals, ad campaigns, and task copy | Load persona by ID; validate against schema; no network I/O |
| **Seller stage router** | Rules-based lifecycle classification from mock profile metrics | `classifySellerStage(profile) → new \| leakage \| growth` with documented thresholds |
| **Workflow task feed** | Map stage + workflow to ranked mock tasks with justification and CTA | `getTasksForWorkflow(workflow, persona) → Task[]` |
| **New Seller Copilot UI** | Onboarding checklist, milestone progress, task cards | Pages/components under web app; Vietnamese copy |
| **Revenue Leakage UI** | Anomaly list, severity, GMV impact, evidence drill-down, fix recommendations | Same task card pattern as other workflows |
| **Growth Copilot UI** | Ad performance summary, scale/cut ranked recommendations | Same task card pattern |
| **Executor (no-op)** | Approve/dismiss state machine; session persistence; no API side effects | `approveTask(id)`, `dismissTask(id)` → local state + analytics only |
| **UX analytics** | Fire structured events for task click, approve, dismiss | Thin wrapper over existing analytics utility |

### Architectural decisions

- **UI-first, mock-only:** No TikTok API calls, no Postgres writes for workflow data in Phase 1. Fixtures live in the web tier (or a shared mock package) and are loaded client-side or via static import.
- **Phase 2 shape preserved:** Data → stage router → workflow selection → ranked tasks → copy → approve/dismiss. Phase 2 swaps mock for API + inference + Ollama; executor becomes real.
- **Rules baseline for ML:** Seller-stage thresholds are explicit constants with tests. Phase 1.5 ML classifier will be compared against this rules output on backtest data.
- **Copy layer:** Hardcoded Vietnamese strings in fixtures. No LLM in Phase 1.
- **Auth:** One-click demo login on the frontend. Mock personas can be selected post-login for demo/testing.
- **Legacy retirement:** Creator-matching routes (`/recommendations`, `/creators`, etc.) redirect or are removed from primary nav per EXECUTION.md cleanup; seller-money workflows become the home experience.
- **Locale:** Vietnamese diacritics, VND ₫ formatting, ICT timezone — consistent with existing `web` conventions.
- **No iOS parity in Phase 1:** Web-only for the 100-seller UX test.
- **Workspace mode retained:** Post-login **Seller vs Affiliate** mode selection stays. **Seller = dark theme** and owns all Phase 1 seller-money workflows. **Affiliate = light theme** and shows a consistent **Out of Scope** state on every route (mode exists for future work; no affiliate workflows in Phase 1). Mode switcher and `localStorage` persistence reuse existing `workspace-mode` conventions.

### Schema assumptions (mock)

- **Seller profile:** `shop_id`, `shop_name`, `shop_age_days`, `order_count_30d`, `return_rate_30d`, `ad_spend_30d_vnd`, `gmv_30d_vnd`
- **Task:** `id`, `workflow`, `type`, `severity`, `title`, `body`, `cta_label`, `estimated_impact_vnd`, `evidence_refs[]`, `copy_source: "mock"`
- **Order/return/affiliate/ad fixtures:** Sufficient for drill-down UI; `buyer_id` masked only; no PII

### API contracts (Phase 1)

- **No new backend endpoints required** for core mock workflows if fixtures are served statically from the web app.
- Optional: lightweight `GET /v1/demo/personas` later — **out of scope for initial slices** unless needed for multi-persona switching; prefer client-side fixture switcher for Phase 1.

### Assumptions

- 100 test sellers are recruited internally or via pilot list; no in-app recruitment flow in Phase 1.
- Engagement threshold numeric target will be set by Product lead before exit gate review.
- Existing analytics instrumentation utility is the event sink unless Product specifies otherwise.
- Parallel TikTok API polling setup (EXECUTION.md parallel track) does not block Phase 1 UI work.

---

## Testing Decisions

### What makes a good test

- Test **observable behavior** through public UI and module interfaces — not implementation details.
- Prefer integration-style tests (React Testing Library) for workflow pages: routing, task render, approve/dismiss state transitions, analytics calls.
- Seller-stage router: unit tests on threshold boundaries with golden fixture profiles.
- Mock schemas: validation tests that fixtures conform to JSON schema.

### Modules to test

| Module | Test style | Priority |
|--------|------------|----------|
| Seller stage router | Unit — boundary cases per persona | High |
| Mock data schemas | Unit — schema validation | High |
| Executor (no-op) | Integration — approve/dismiss updates UI state | High |
| Workflow UIs (×3) | Integration — renders tasks, empty states, Vietnamese copy | High |
| UX analytics | Unit — events fired on click/approve/dismiss | Medium |

### Prior art

- Existing web UI test suite — Jest + React Testing Library patterns for pages/navigation.
- Existing mock-data utilities — prior conventions for fixtures and demo flows.

---

## Out of Scope

Per [`EXECUTION.md`](../../../EXECUTION.md) — explicitly **not** in Phase 1:

- Real TikTok API calls (Orders, Products, Affiliate, Ads)
- ML models (seller stage classifier, anomaly detector, ad performance analyzer)
- Ollama or any LLM copy layer
- Live task execution against TikTok APIs
- Postgres persistence of workflow tasks or approvals (session/local only)
- Phase 1.5 backtest data pipeline
- Creator ↔ Shop matching (Phase 3+)
- Celery, Kafka, multi-node workers
- iOS app parity for new workflows
- Nav redesign as a standalone feature
- Seller OS / CRM surfaces (inventory, settlements, livestreams as primary workflows)
- Web analytics dashboard for Product (instrumentation only; dashboard is Later)
- `src/` folder reshaping

---

## Further Notes

### EXECUTION.md slice mapping

| Slice | PRD coverage |
|-------|----------------|
| P1-1 Mock data schemas | User stories 38–42; Mock data layer module |
| P1-2 New Seller Copilot UI | User stories 8–14 |
| P1-3 Revenue Leakage Detection UI | User stories 15–21 |
| P1-4 Growth Copilot UI | User stories 22–27 |
| P1-5 Executor approval flow (no-op) | User stories 28–33 |
| P1-6 Rules-based seller-stage detection | User stories 34–37 |
| P1-7 UX instrumentation | User stories 43–47 |

### Risks

| Risk | Mitigation |
|------|------------|
| Legacy UI confuses test sellers | Aggressive redirects; single home entry to seller-money workflows |
| Mock data feels unrealistic | Vietnamese-native copy review; volumetric fixtures |
| Engagement threshold undefined | Product lead sets threshold before Week 6 gate review |
| Scope creep into API/ML | EXECUTION.md governance; PRs must cite slice; no real API in P1 |

### Rollout

- Internal dogfood → 100-seller pilot → exit gate review with Product lead.
- No production feature flags required; mock mode is the only mode in Phase 1.

### Observability

- Structured analytics events: `task_clicked`, `task_approved`, `task_dismissed` with `workflow`, `task_type`, `persona_id`, `session_id`.
- No PII in event payloads.

### Phase 1 engagement threshold (exit gate)

**Definition:** Phase 1 UX validation passes when **≥ 60%** of participating test sellers complete at least one task approval (`task_approved`) in **each** of the three workflows (`new_seller`, `leakage`, `growth`) during their test session.

**Measurement:**

| Metric | Formula |
|--------|---------|
| Per-workflow approval rate | Unique `session_id` with ≥ 1 `task_approved` for that `workflow` ÷ total unique test sellers |
| Exit gate | All three workflow rates ≥ 60% |

**Data sink:** `juli:analytics` `CustomEvent` bus on the web client (`web/src/lib/ux-analytics/`). Export for the 100-seller pilot via a devtools listener or scripted session capture; no in-app dashboard in Phase 1.

**Minimum sample:** 100 test sellers per EXECUTION.md exit gate.

**Adjustment:** Product lead may revise the 60% target before the Week 6 gate review; update this section when finalized.

### Follow-ups (Phase 1.5+)

- Replace rules router with ML seller-stage classifier.
- Train anomaly and ad models on backtest parquet.
- Publish `docs/architecture/target-v2.md` at end of Phase 1.5.

---

## Deep modules summary (for to-issues)

1. **Mock data layer** — schemas, personas, task copy fixtures
2. **Seller stage router** — deterministic rules + tests
3. **New Seller Copilot UI** — onboarding task flow
4. **Revenue Leakage UI** — anomaly surfacing + fix recommendations
5. **Growth Copilot UI** — ad read + scale/cut suggestions
6. **Executor (no-op)** — approve/dismiss UX + session state
7. **UX analytics** — task click + approval instrumentation
