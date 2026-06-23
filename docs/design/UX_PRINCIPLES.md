# Juli AI — UX Principles

> Interaction and information-design rules for the Juli seller workspace. Complements
> [PRODUCT.md](./PRODUCT.md) and [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md).

## Core product principles

From [ADR-007](../decisions/014-decision-copilot-app-structure-and-journey.md):

1. **Mobile-first** — single-thumb operation; 44×44px minimum touch targets.
2. **Minimal cognitive load** — each screen answers one primary question.
3. **Recommendation-first** — Decisions tab is the action hub; Home is visibility only.
4. **Workflow complexity hidden by default** — templates demoted to sub-tab.
5. **Human approval required** — no autonomous execution; approve only on Decisions.
6. **Clear business impact** — every Decision shows estimated impact + confidence.
7. **Explain why** — reasoning expandable on every recommendation.

## Screen mental models

| Screen | Question | Allowed actions | Forbidden on screen |
|--------|----------|-----------------|---------------------|
| Home | What is happening? | Explore metrics, read Juli suggestions, navigate to Decisions | Approve, dismiss, execute workflows |
| Decisions | What should I do? | Review, expand reasoning, approve/reject, open detail flow | — |
| Juli Chat | Help me understand? | Ask about metrics, decisions, platform | Replace Decisions approval flow |

## Home vs Decisions separation

**Home = explore.** Chart-first dashboard: shop info → Báo cáo hôm nay → Shop Health.

**Decisions = act.** Full ranked list, approval gate, in-progress tracking, workflow
modals (`ListingWorkflowPanel`, `LeakageWorkflowPanel`).

Do not put on Home:

- Task queues or Tiến độ gần đây
- RRAA / pipeline stage labels
- Persona copilot panels (`NewSellerCopilotPanel`, `GrowthCopilotPanel`, `LeakageCopilotPanel`)
- Approve / dismiss CTAs
- Top-N decision preview cards (current implementation — decisions live on `/decisions` only)

## Metric tile interaction model

Two-step flow on Home metric tiles:

1. **Tap tile** → expand inline **Gợi ý từ Juli** (blue `--info` icon + accordion).
2. **Secondary action** → navigate to `/decisions?highlight=<workflow_id>`.

Additional affordances:

- **Estimated bar segment** (`RealEstimatedBar`) — subtle glow on projected portion;
  tap → same Decisions highlight link.
- **Journey inbound** — `?highlight=<domain>:<metric>` auto-selects Báo cáo tab, scrolls
  and pulses target chart.

Copy on Home stays **minimal** — chart + label + delta; detail lives in suggestion expand
or Decisions.

## RRAA journey loop (cross-screen, invisible stages)

Reward → Reason → Action → Anticipation connects Home charts to Decisions cards **without
labeling stages in UI**.

| Direction | Mechanism |
|-----------|-----------|
| Home → Decisions | `buildDecisionsHighlightLink(workflowId)` → `?highlight=` scrolls + rings matching `ClarityCard` |
| Decisions → Home | **Xem trên Trang chủ →** on Anticipation copy → `buildHomeHighlightLink(anchor)` |

Hooks: `useHomeJourneyHighlight`, `useJourneyHighlight`. Registry: `journey-loop.ts`.

OpenDesign should preserve this loop visually — highlight rings, tab auto-switch, and
return link are first-class UX, not decoration.

## Decision detail flow (5 steps)

Opened from **Review** on a `ClarityCard` at `/decisions/[decisionId]`:

| Step | Purpose | Seller outcome |
|------|---------|----------------|
| 1. Why | Explain recommendation | Trust + context |
| 2. Analytics | Supporting data | Evidence |
| 3. Inputs | Collect required decisions | Budget, SKU, tolerance, etc. |
| 4. Preview | Impact + risks | Informed consent |
| 5. Approve | Execute or no-op | Routes to workflow modal per ADR-007 |

Step indicator: `DecisionDetailStepIndicator`. Back navigation preserves scroll on
Decisions Recommended tab.

## Decisions sub-tab behavior

| Tab | Content | Empty state |
|-----|---------|-------------|
| Recommended | `OperationsApprovalShell` + `ClarityCard` list | Explain collecting data / no recommendations |
| In Progress | `DecisionsInProgressShell` | No active decisions message |
| Workflow Templates | `DecisionsWorkflowTemplatesShell` | Advanced settings only |

## Juli AI Chat principles

- **Contextual** — suggested prompts tied to workspace mode and active decision
  (`saveActiveDecisionForChat`).
- **Assistive** — explain metrics, compare products, clarify platform policy.
- **Not a replacement** for Decisions approval or workflow execution.
- Phase 1: mock replies; layout uses sticky chat input above bottom nav.

## Vietnamese copy standards

- All user-visible strings in Vietnamese with full diacritics.
- Errors: state problem + recovery (e.g. "Mã OTP không đúng. Vui lòng thử lại.").
- Empty states: why empty + what to do (`CollectingDataEmpty` pattern).
- Money: always `formatVND` — never hand-format ₫.
- Dates: ICT via `formatDate` / `formatDateTime`.

## Accessibility

| Requirement | Standard |
|-------------|----------|
| Text contrast | WCAG AA 4.5:1 |
| UI component contrast | 3:1 |
| Touch targets | ≥ 44×44px (`NavBar`, metric tiles, CTAs) |
| Forms | `<label htmlFor>` or `aria-label`; errors via `aria-describedby` |
| Modals | Focus trap, `aria-modal`, labelled title |
| Tabs | `role="tablist"` / `role="tab"` / `aria-selected` (Báo cáo domain switcher) |
| Expandable tiles | `aria-expanded` on metric accordions |
| Live feedback | `aria-live` for async states |
| Icon-only controls | `aria-label` |
| Reduced motion | Disable glow/pulse/stagger when `prefers-reduced-motion` |

## Responsive behavior

| Breakpoint | Home behavior |
|------------|---------------|
| Mobile (~375px) | Single column stack; horizontal scroll on domain tabs |
| Desktop (≥1024px) | `.seller-home-grid` — sidebar shop info + main dashboard |

Decisions and Chat remain `max-w-lg` centered column with bottom nav.

## Loading, empty, and error states

| State | Pattern |
|-------|---------|
| Initial load | `.skeleton` placeholders (`SellerHomeSkeleton`, `DecisionsSkeleton`) |
| No API data | Graceful empty components — never blank screen |
| Demo mode | `DemoModeNotice` on task flows |
| Affiliate mode | `AffiliateOutOfScope` on all authenticated routes |

## Performance UX

- Pages target **<2s load** (Core Web Vitals per `web/MODULE.md`).
- Home stays lightweight — heavy approval UI loads only on Decisions.
- Chart animations gated by `prefers-reduced-motion`.

## Financial data in UI

Seller financial fields (revenue, ROAS, ad spend, etc.) may appear in formatted UI but:

- Must not leak into logs, LLM prompts, or handoff docs in raw form.
- Prefer deltas, trend direction, and tier labels in advisory copy.
- Evidence drawers use masked drill-down where applicable (`EvidenceDrawer`).

## UX anti-patterns

| Anti-pattern | Why |
|--------------|-----|
| Task-first Home | Violates read-only Home contract |
| RRAA labels in UI | Stages are implementation detail |
| Generic AI purple gradients | `--info` blue is reserved for Juli suggestions |
| English placeholders | Breaks locale invariant |
| Silent `div` chart clicks | Fails keyboard/a11y |
| Approval from Home | Breaks human-in-the-loop model |
| Fourth nav tab | ADR-007 locked at 3 tabs |

## Canonical test coverage (regression anchors)

| Behavior | Test file |
|----------|-----------|
| Home read-only | `test_issue193_home_read_only.test.tsx` |
| Báo cáo hôm nay | `test_issue194_todays_report.test.tsx` |
| RRAA loop | `test_issue221_rraa_loop.test.tsx` |
| Juli suggestion accordion | `test_issue229_juli_suggestion_accordion.test.tsx` |
| Decision detail + Home link | `test_issue233_decision_detail_home_link.test.tsx` |
| Responsive grid | `test_issue231_seller_home_grid.test.tsx` |
