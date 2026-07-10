# PRD: MVP 1.8.5 — Decision Copilot App Structure (P1.8-9)

> **Phase:** 1.8 (Weeks 11–13) · **Slice:** P1.8-9 · **Product label:** Phase 1.8.5 · **Authority:** [`EXECUTION.md`](../../../EXECUTION.md) · **Design:** [`docs/architecture/system-design.md`](../../architecture/system-design.md) § Decision Copilot app structure · **ADR:** [ADR-028](../../adr/028-decision-copilot-app-structure.md)
>
> **GitHub parent issue:** [#190](https://github.com/thienphung00/Juli-AI/issues/190)
>
> **Depends on:** P1.8-3 (health), P1.8-4 (ranking); relocates P1.8-5…7 surfaces from Home into Decisions.
>
> **Related:** [ADR-027](../../adr/027-design-system-token-foundation.md) (tokens) · orchestration PRD [`PRD-orchestration.md`](PRD-orchestration.md) · design polish [`PRD.md`](PRD.md) (#174)

---

## Problem Statement

Phase 1.8 built an operations pipeline spine (classify → health → rank → reason → approve → execute → track outcomes) but mounted **everything on Home**: Shop Health hero, full ranked recommendation cards, approval toolbar, and outcome views all live on `/`. Sellers land on a screen that asks them to approve before they understand shop status — cognitive overload that conflicts with Juli’s **Decision Copilot** positioning: analyze, recommend, collect decisions, execute **only after explicit approval**.

Bottom navigation has only two tabs (Home + Juli Chat). There is no dedicated workspace for reviewing decisions, tracking in-progress work, or configuring workflow templates. The seller canvas uses a pink-tinted background (`#FEF5F6`) that feels decorative rather than calm and professional; product direction is a **clean white canvas** with pink reserved for accent (health bars, key CTAs).

Sellers need three clear mental models:
- Home → *"What is happening?"* (read-only)
- Decisions → *"What should I do?"* (review, approve, configure)
- Juli Chat → *"Help me understand and complete this."* (contextual)

Without this IA restructure, Phase 2 would wire live APIs into a landing page that mixes visibility and action — undermining trust and human-in-the-loop guardrails.

---

## Solution

Adopt exactly **three main tabs** for the seller workspace ([ADR-028](../../adr/028-decision-copilot-app-structure.md)) and introduce **Decision** as the primary seller-facing object (wrapping one validated `workflow_id` from the six-workflow catalog).

**Visual foundation:** Seller workspace uses a **white canvas** (`#FFFFFF`) for page background, header, and muted surfaces — not the pink-tint `#FEF5F6`. Brand pink (`#F86BA5`) remains for accents only (shop health progress, primary CTAs, Juli tab highlight). Affiliate workspace stays dark per ADR-027.

### Tab 1: Home (`/`)

Read-only. **No approvals or workflow execution on Home.**

1. **Shop Status (hero)** — Shop Health Score, Account Health Rating, platform alerts/messages/violations.
2. **Today's Report** — one container with animated switching across five domains: Revenue Growth, Revenue Protection, Product Listings, Advertising, Refunds. Each card: current status, trend vs prior period, metric deltas.
3. **Recommended Decisions Preview** — top 3 highest-impact decisions (title, estimated impact, revenue gain or loss-prevention value) + **"Xem tất cả quyết định"** → `/decisions`.

### Tab 2: Decisions (`/decisions`)

Three sub-tabs:

| Sub-tab | Purpose |
|---------|---------|
| **Recommended** | Full ranked decision cards with confidence, reasoning, required inputs, Review CTA |
| **In Progress** | Approved decisions: `needs_input`, `executing`, `completed` |
| **Workflow Templates** | Advanced settings (thresholds, automation rules) — not primary UX |

Hosts approval gate (P1.8-6), reasoning expansion (P1.8-5), outcome entry (P1.8-7).

**Decision detail flow** (from Review): (1) Why → (2) Analytics → (3) User inputs → (4) Execution preview → (5) Approve and execute.

### Tab 3: Juli AI Chat (`/ai-chat`)

Contextual assistant connected to active/recent decisions — explain recommendations, compare products, clarify metrics, assist completion, answer platform questions. Not a generic chatbot.

---

## User Stories

### White canvas & navigation

1. As a **seller**, I want the app background to be clean white, so that the interface feels professional and calm during long sessions.
2. As a **seller**, I want pink used only for accents (health bar, key CTAs), so that color earns meaning and does not dominate the screen.
3. As a **seller**, I want three bottom-nav tabs (Trang chủ, Quyết định, Juli), so that I always know where to look for status vs action vs help.
4. As a **seller on mobile**, I want 44×44px touch targets on all nav items, so that I can navigate one-handed.
5. As a **developer**, I want seller `--background` and related muted surfaces set to white (`#FFFFFF`), not `#FEF5F6`, so that the token layer matches product direction.
6. As a **QA engineer**, I want visual regression covering white seller canvas, so that pink background does not regress.

### Home — Shop Status

7. As a **seller**, I want Shop Health Score and Account Health Rating at the top of Home, so that I immediately see platform visibility.
8. As a **seller**, I want platform alerts, messages, and violations surfaced in the hero, so that I know if something needs attention on TikTok.
9. As a **seller**, I want Home to answer *"How is my shop visibility right now?"* without asking me to approve anything, so that I can orient before acting.

### Home — Today's Report

10. As a **seller**, I want a Today's Report summarizing five business domains in one container, so that I see cross-domain health at a glance.
11. As a **seller**, I want smooth animated switching between Revenue Growth, Revenue Protection, Product Listings, Advertising, and Refunds domains, so that scanning feels intentional not cluttered.
12. As a **seller**, I want each domain card to show current status, trend vs prior period, and metric deltas, so that I understand direction not just snapshots.
13. As a **seller with reduced-motion preference**, I want domain switching to respect `prefers-reduced-motion`, so that the app does not animate against my settings.

### Home — Decision preview (read-only)

14. As a **seller**, I want only the top 3 highest-impact decisions previewed on Home, so that I am not overwhelmed on landing.
15. As a **seller**, I want each preview to show title, estimated impact, and revenue gain or loss-prevention value, so that I understand why they matter.
16. As a **seller**, I want a **"Xem tất cả quyết định"** link to the Decisions tab, so that I can dive deeper when ready.
17. As a **seller**, I want **no approve, dismiss, or execute controls on Home**, so that I never accidentally trigger a workflow from the status screen.
18. As a **QA engineer**, I want automated tests asserting zero approve CTAs on Home, so that the read-only contract is CI-enforced.

### Decisions — Recommended

19. As a **seller**, I want all ranked decisions on the Recommended sub-tab, so that I have one place to review what Juli suggests.
20. As a **seller**, I want each decision card to show title, estimated impact, confidence, AI reasoning summary, required user inputs, and status, so that I can prioritize informed action.
21. As a **seller**, I want a **Review** button on each card opening the detail flow, so that I understand before approving.
22. As a **seller**, I want approve-all, selective approve, and reject-with-reason on Decisions only, so that approval is deliberate.
23. As a **seller**, I want approving NPL or Refund Spike to open the existing listing/leakage modals, so that executable journeys continue seamlessly.
24. As a **seller**, I want deferred workflow approvals to show a clear no-op toast, so that I am not misled.

### Decisions — In Progress

25. As a **seller**, I want approved decisions listed under In Progress, so that I can track what Juli is working on.
26. As a **seller**, I want statuses **Needs Input**, **Executing**, and **Completed**, so that I know what requires my attention.
27. As a **seller**, I want to resume a `needs_input` decision from In Progress, so that I can finish required fields.

### Decisions — Workflow Templates

28. As a **power seller**, I want Workflow Templates as an advanced sub-tab, so that I can tune thresholds and automation without cluttering the main flow.
29. As a **seller**, I want template settings grouped by workflow (Budget Optimization, Stockout Prevention, etc.), so that configuration maps to decisions I recognize.
30. As a **product owner**, I want Templates not to be the default Decisions landing, so that recommendation-first UX stays primary.

### Decision detail flow

31. As a **seller**, I want step 1 to explain why the recommendation exists, so that I trust the suggestion.
32. As a **seller**, I want step 2 to show supporting analytics, so that I see evidence behind the recommendation.
33. As a **seller**, I want step 3 to collect required inputs (product selection, budget limits, campaign goals, risk tolerance), so that execution matches my intent.
34. As a **seller**, I want step 4 to preview expected revenue impact, loss prevention, confidence, and risks, so that I know tradeoffs before committing.
35. As a **seller**, I want step 5 to approve and execute (or no-op for deferred workflows), so that one flow closes the loop.
36. As a **seller using keyboard**, I want the detail stepper focusable with visible focus rings, so that the flow is accessible.

### Juli AI Chat — contextual

37. As a **seller**, I want chat suggested prompts tied to my current or recent decision, so that Juli helps me complete what I am reviewing.
38. As a **seller**, I want to ask Juli to explain a recommendation, compare products, or clarify metrics, so that I do not need to leave the app for answers.
39. As a **seller**, I want chat to avoid generic assistant small talk, so that Juli feels like a decision copilot not a chatbot.
40. As a **developer**, I want chat context derived from decision state (mock in P1.8-9), so that P2 can swap live decision IDs without UI rewrite.

### Migration & legacy

41. As a **seller** bookmarking `/recommendations`, I want to land on `/decisions`, so that old links still work.
42. As a **developer**, I want `web/MODULE.md` updated with new routes and 3-tab IA, so that contributors follow the contract.
43. As a **developer**, I want `OperationsPipelineShell` split — summary on Home, action on Decisions — so that pipeline logic is not duplicated.

### Traceability & governance

44. As a **product owner**, I want decisions to map only to the six validated workflows (ADR-026), so that the catalog constraint holds in the new IA.
45. As a **developer**, I want a `Decision` view-model wrapping `workflow_recommendations` envelopes, so that UI speaks in decisions while execution stays workflow-keyed.

---

## Implementation Decisions

### Modules (by responsibility)

| Module | Responsibility | Public interface |
|--------|----------------|------------------|
| **Seller canvas tokens** | White background for seller mode | `--background: #FFFFFF`; remove pink tint from page/header/muted |
| **Bottom navigation** | 3 tabs: Home, Decisions, Juli | `BOTTOM_NAV_TABS` + active-state helpers |
| **Decision view-model** | Map recommendations → Decision + lifecycle status | `toDecision()`, `DecisionStatus` types |
| **Home shell** | Read-only: hero + Today's Report + top-3 preview | `HomeSummaryShell` (split from pipeline shell) |
| **Today's Report** | Domain cards + animated switcher | `TodaysReportPanel`, domain summary loaders |
| **Decisions shell** | Sub-tabs + approval host | `DecisionsPage`, `DecisionsSubTabs` |
| **Decision detail** | 5-step guided flow | `DecisionDetailFlow` on `/decisions/[id]` |
| **Chat context** | Wire active decision into Juli prompts | Context provider or URL param bridge |
| **Legacy redirects** | `/recommendations` → `/decisions` | `legacy-redirects.js` update |

### Architectural decisions

- **ADR-028 authoritative** for 3-tab IA, Decision as primary object, Home read-only.
- **ADR-026 unchanged** for pipeline envelopes, six workflows, approval routing rules.
- **White canvas override:** Seller `--background`, `--header-background`, and `--muted` use `#FFFFFF` (not ADR-027 `#FEF5F6` pink tint). Pink `#F86BA5` stays accent-only. Coordinate with #174 so token migration does not reintroduce pink canvas.
- **Split, don't duplicate:** `useOperationsPipeline` and `useOperationsApproval` shared; only component placement changes.
- **Vietnamese labels:** Trang chủ · Quyết định · Juli (bottom nav).
- **No new backend:** Mock data only; no API/Postgres/ML changes.

### Assumptions

- P1.8-3 (#178) and P1.8-4 (#179) merged before Decisions content ships; nav + white canvas can land earlier.
- P1.8-5 (#180) and P1.8-6 (#181) reasoning/approval components relocate into Decisions tab.
- Affiliate workspace unchanged (dark theme); white canvas applies to seller mode only.
- Workflow Templates sub-tab ships with mock settings UI (no live TikTok config in P1.8-9).

---

## Testing Decisions

- **Home read-only gate:** integration test asserts no `approve`, `approve-all`, or `ApprovalGateToolbar` on `/`.
- **Nav:** test 3 tabs render; `/decisions` route loads; active state per pathname.
- **White canvas:** test seller mode computed `--background` is white (not `#FEF5F6`).
- **Decision mapping:** unit tests for `toDecision()` from mock `workflow_recommendations`.
- **Detail flow:** step navigation + approve routes to executor mock per workflow_id.
- **E2E:** persona → Home preview (3 cards max) → Decisions → Review → approve NPL → listing modal.
- Prior art: `test_operations_approval_gate.test.tsx`, `test_clarity_card_reasoning.test.tsx`, nav tests from #123.

---

## Out of Scope

- TikTok API, Postgres, ML, Ollama
- Fourth main tab or per-copilot tabs (New Seller / Growth / Leakage as nav)
- Live workflow template persistence to backend
- Affiliate workspace IA changes
- Inventing decisions outside the six validated workflows
- Approval or execution from Home

---

## Further Notes

- Re-baseline `screenshots/` after white canvas + 3-tab IA land.
- P1.8 exit gate adds ADR-028 verification (Home read-only; Decisions hosts approval).
- Product lead to confirm Today's Report default domain on first load (suggest Revenue Growth for MID_LARGE_SHOP, Product Listings for NEW_SHOP).
