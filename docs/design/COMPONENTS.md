# Juli AI — Component Catalog

> Inventory of design-relevant UI components in `web/src/components/`. Grouped by feature.
> Page files in `web/src/app/` stay thin — they compose these exports.

## Shell & navigation

| Component | Path | Role |
|-----------|------|------|
| `AuthenticatedShell` | `AuthenticatedShell.tsx` | Page wrapper: header, main, optional sticky footer, `NavBar` |
| `PageHeader` | `PageHeader.tsx` | Sticky top bar; `ShopInfoHeader` when shop metadata present |
| `NavBar` | `NavBar.tsx` | Fixed bottom 3-tab navigation |
| `ModeSwitcher` | `ModeSwitcher.tsx` | Seller / affiliate workspace toggle |
| `AffiliateOutOfScope` | `AffiliateOutOfScope.tsx` | Vietnamese placeholder for affiliate mode |
| `LegacyRouteRedirect` | `LegacyRouteRedirect.tsx` | Client redirect for deprecated routes |
| `DemoControlsDrawer` | `DemoControlsDrawer.tsx` | Dev/demo fixture controls |

## Auth

| Component | Path | Role |
|-----------|------|------|
| `LoginForm` | `LoginForm.tsx` | Phone-OTP login with validation and error states |

## Seller Home

| Component | Path | Role |
|-----------|------|------|
| `SellerHomeShell` | `seller-home/SellerHomeShell.tsx` | Home entry; persona loading skeleton |
| `HomeSummaryShell` | `workflows/operations/HomeSummaryShell.tsx` | Grid layout: shop info + report + health |
| `PersonaSwitcher` | `seller-home/PersonaSwitcher.tsx` | Demo persona selection (not on chart-first Home) |

## Shop info & health

| Component | Path | Role |
|-----------|------|------|
| `ShopInfoHeader` | `workflows/operations/ShopInfoHeader.tsx` | Compact shop name + status in header |
| `ShopInfoCard` | `workflows/operations/ShopInfoCard.tsx` | Sidebar shop card variant |
| `ShopHealthCard` | `workflows/operations/ShopHealthCard.tsx` | SPS/AHR health section container |
| `ShopHealthHero` | `workflows/operations/ShopHealthHero.tsx` | Hero variant (legacy/pipeline contexts) |
| `HealthMetricBar` | `workflows/operations/HealthMetricBar.tsx` | 5-segment pink score bar + threshold ticks |

## Báo cáo hôm nay (Today's Report)

| Component | Path | Role |
|-----------|------|------|
| `TodaysReportPanel` | `home/todays-report/TodaysReportPanel.tsx` | Domain tab switcher + active domain card |
| `TodaysReportDomainCard` | `home/todays-report/TodaysReportDomainCard.tsx` | Metric tiles for one domain |
| `ReportMetricChart` | `home/todays-report/ReportMetricChart.tsx` | Recharts sparkline / bar per metric |
| `MetricSparkline` | `home/todays-report/MetricSparkline.tsx` | Compact sparkline primitive |

**Supporting lib:** `lib/operations/todays-report.ts` — domain IDs, summaries, default tab.

## Metric affordances

| Component | Path | Role |
|-----------|------|------|
| `RealEstimatedBar` | `workflows/operations/RealEstimatedBar.tsx` | Real vs estimated segments; glow + Decisions link |
| `JourneyEmphasisText` | `workflows/operations/JourneyEmphasisText.tsx` | RRAA copy emphasis styling |

**Supporting lib:** `lib/operations/metric-action-mapping.ts`, `journey-loop.ts`.

## Decisions & recommendations

| Component | Path | Role |
|-----------|------|------|
| `DecisionsPage` | `DecisionsPage.tsx` | Decisions tab page with sub-tabs |
| `DecisionsSubTabs` | `decisions/DecisionsSubTabs.tsx` | Recommended / In Progress / Templates tabs |
| `OperationsApprovalShell` | `workflows/operations/OperationsApprovalShell.tsx` | Recommended list + approval session |
| `ClarityCard` | `workflows/operations/ClarityCard.tsx` | Primary Decision card — impact, reasoning, actions |
| `DecisionPreviewCard` | `workflows/operations/DecisionPreviewCard.tsx` | Compact decision preview variant |
| `RecommendedDecisionsPreview` | `workflows/operations/RecommendedDecisionsPreview.tsx` | Top-N preview (retained; not on current Home) |
| `ReasoningPanel` | `workflows/operations/ReasoningPanel.tsx` | Why / Impact / Next steps expandable block |
| `ApprovalGate` | `workflows/operations/ApprovalGate.tsx` | `ApprovalGateToolbar`, `OperationsRecommendationsList` |
| `DecisionsInProgressShell` | `decisions/DecisionsInProgressShell.tsx` | In-progress decision list |
| `DecisionsWorkflowTemplatesShell` | `decisions/DecisionsWorkflowTemplatesShell.tsx` | Template / threshold settings |
| `CollectingDataEmpty` | `recommendations/CollectingDataEmpty.tsx` | Empty recommendations state |

## Decision detail flow

| Component | Path | Role |
|-----------|------|------|
| `DecisionDetailPage` | `decisions/DecisionDetailPage.tsx` | Route wrapper for detail flow |
| `DecisionDetailFlow` | `decisions/DecisionDetailFlow.tsx` | 5-step stepper + approve path |
| `DecisionDetailStepIndicator` | `decisions/DecisionDetailStepIndicator.tsx` | Progress indicator across steps |
| `WorkflowTemplateGroup` | `decisions/WorkflowTemplateGroup.tsx` | Grouped template settings UI |

**Supporting lib:** `lib/decisions/` — `toDecision`, detail steps, analytics builders.

## Tasks & workflow execution

| Component | Path | Role |
|-----------|------|------|
| `TaskCard` | `tasks/TaskCard.tsx` | Task queue card with approve/dismiss |
| `TaskQueue` | `tasks/TaskQueue.tsx` | List of active tasks |
| `TaskDismissModal` | `tasks/TaskDismissModal.tsx` | Skip-with-reason modal |
| `TaskExecutorModals` | `tasks/TaskExecutorModals.tsx` | Routes to workflow panels on approve |
| `TaskFeedbackBanner` | `tasks/TaskFeedbackBanner.tsx` | Post-action feedback |
| `DemoModeNotice` | `tasks/DemoModeNotice.tsx` | Demo mode disclosure |

## Workflow panels (modals)

| Component | Path | Role |
|-----------|------|------|
| `ListingWorkflowPanel` | `workflows/new-seller/listing/` | NPL executable flow (mock export) |
| `NewSellerCopilotPanel` | `workflows/new-seller/NewSellerCopilotPanel.tsx` | New seller copilot (retired from Home) |
| `LeakageWorkflowPanel` | `workflows/leakage/LeakageWorkflowPanel.tsx` | Refund spike / leakage journeys |
| `EvidenceDrawer` | `workflows/leakage/EvidenceDrawer.tsx` | Masked evidence drill-down |
| `AdPerformanceSummary` | `workflows/growth/AdPerformanceSummary.tsx` | Growth copilot reference UI |
| `GrowthCopilotPanel` | (growth/) | Growth copilot (retired from Home) |

## Operations pipeline (legacy composite)

| Component | Path | Role |
|-----------|------|------|
| `OperationsPipelineShell` | `workflows/operations/OperationsPipelineShell.tsx` | Full pipeline on one screen (split per ADR-007) |
| `OutcomeTrackingView` | `workflows/operations/OutcomeTrackingView.tsx` | Post-execution outcome metrics |
| `HomePage` | `HomePage.tsx` | Top-level Home page composer |
| `ClarityCard` | (see above) | Shared between Decisions and pipeline |

## Juli AI Chat

| Component | Path | Role |
|-----------|------|------|
| `AiChatPage` | `AiChatPage.tsx` | Chat tab page |
| `ChatMessageList` | `ai-chat/ChatMessageList.tsx` | Message thread |
| `ChatInput` | `ai-chat/ChatInput.tsx` | Text input + send |
| `SuggestedPrompts` | `ai-chat/SuggestedPrompts.tsx` | Contextual prompt chips |

## Legacy / out-of-scope pages

Retained for redirects or pre-MVP history; not canonical seller IA:

| Component | Path |
|-----------|------|
| `TrendsPage` | `TrendsPage.tsx` |
| `InventoryPage` | `InventoryPage.tsx` |
| `OrdersPage` | `OrdersPage.tsx` |
| `AlertsPage` | `AlertsPage.tsx` |

## CSS component classes (not React)

Defined in `web/src/app/globals.css` `@layer components`:

`.card`, `.glass`, `.app-header`, `.brand-wordmark`, `.btn-primary`, `.btn-secondary`,
`.field-input`, `.badge*`, `.spinner`, `.skeleton`, `.safe-area-*`, `.seller-home-grid`.

Prefer these primitives over ad-hoc Tailwind when styling new surfaces.

## Component composition patterns

### Card with actions

Reference: `TaskCard.tsx` — bordered `.card`, primary/dismiss buttons, `data-testid`,
disposition states.

### Expandable reasoning

Reference: `ClarityCard.tsx` — chevron expand, `ReasoningPanel`, journey Home link on
Anticipation.

### Metric tile with suggestion

Reference: `TodaysReportDomainCard.tsx` — chart, delta badge, Juli suggestion accordion,
Decisions CTA.

### Modal workflow

Reference: `LeakageWorkflowPanel.tsx` — step progress, primary action, dismiss path.

### Empty state

Reference: `CollectingDataEmpty.tsx` — illustration area, Vietnamese explanation, CTA.

## `data-testid` conventions

Stable, kebab-case, role-oriented:

| Pattern | Examples |
|---------|----------|
| Shell | `seller-home-shell`, `decisions-recommended-shell` |
| Feature | `todays-report-panel`, `shop-health-card` |
| Actions | `task-approve`, `task-dismiss` |
| Tabs | `todays-report-tab-revenue_growth` |
| Forms | `login-phone-input`, `login-submit` |

Add testids for: primary actions, empty states, modals, expandable regions under test.

## Hooks & context (design-relevant)

| Export | Path | Role |
|--------|------|------|
| `useDemoPersona` | `lib/demo-persona-context.tsx` | Mock persona for fixtures |
| `useWorkspaceMode` | `lib/mode-context.tsx` | Seller/affiliate + theme |
| `useHomeJourneyHighlight` | `lib/operations/use-home-journey-highlight.ts` | Home inbound highlight |
| `useJourneyHighlight` | `lib/operations/use-journey-highlight.ts` | Decisions inbound highlight |
| `usePrefersReducedMotion` | `hooks/use-prefers-reduced-motion.ts` | Motion gating |
| `useOperationsPipeline` | `lib/operations/use-operations-pipeline.ts` | Home data envelope |
| `useOperationsApproval` | `lib/operations/use-operations-approval.ts` | Decisions approval session |

## OpenDesign component priorities

| Priority | Components | Why |
|----------|------------|-----|
| P0 | `TodaysReportPanel`, `ReportMetricChart`, `ClarityCard`, `ShopHealthCard` | Primary seller surfaces |
| P1 | `DecisionDetailFlow`, `ReasoningPanel`, `RealEstimatedBar` | Decision trust + journey loop |
| P2 | `NavBar`, `PageHeader`, `LoginForm`, `ChatMessageList` | Shell consistency |
| P3 | Workflow modals, legacy pages | Polish after core loop |

## Related docs

- [SCREENS.md](./SCREENS.md) — route → component mapping
- [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md) — tokens and primitives
- [`web/MODULE.md`](../../web/MODULE.md) — public interface authority
