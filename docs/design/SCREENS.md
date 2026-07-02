# Juli AI — Screens & Routes

> Screen-by-screen baseline for OpenDesign. Routes live under `web/src/app/`. Shell:
> `AuthenticatedShell` (header + main + bottom `NavBar`) for authenticated seller views.

## Navigation shell

```
┌─────────────────────────────────────┐
│ PageHeader (sticky, shop info)      │
├─────────────────────────────────────┤
│                                     │
│   main (.app-container)             │
│   pb-24 clears fixed bottom nav     │
│                                     │
├─────────────────────────────────────┤
│ NavBar — Trang chủ | Quyết định | Juli │
└─────────────────────────────────────┘
```

Bottom nav (`BOTTOM_NAV_TABS` in `lib/nav-config.ts`):

| Label | Route | Icon |
|-------|-------|------|
| Trang chủ | `/` | Home |
| Quyết định | `/decisions` | ListChecks |
| Juli | `/ai-chat` | Sparkles |

Active state: `isNavTabActive(pathname, href)`. Minimum touch target 44×44px.

---

## Unauthenticated

### `/login`

| Attribute | Detail |
|-----------|--------|
| Component | `LoginForm` |
| Purpose | One-click demo login |
| Layout | Centered form, brand wordmark |
| States | Continue → loading → error |

### `/mode-select`

| Attribute | Detail |
|-----------|--------|
| Purpose | Post-login workspace gate: Seller vs Affiliate |
| Behavior | Skipped when `juli_workspace_mode` already persisted |
| Note | Affiliate selects dark theme + out-of-scope shell |

---

## Seller workspace — main tabs

### `/` — Trang chủ (Home)

| Attribute | Detail |
|-----------|--------|
| Page | `app/page.tsx` → `HomePage` → `SellerHomeShell` |
| Shell title | Trang chủ (via `PageHeader` / shop metadata) |
| User question | What is happening? |
| Mode | **Read-only** — no approvals |

**Layout (desktop grid):**

```
┌──────────────┬────────────────────────────────────┐
│ ShopInfoCard │ Báo cáo hôm nay (TodaysReportPanel) │
│  (sidebar)   │  - domain tabs (horizontal scroll)  │
│              │  - metric tiles + charts            │
│              ├────────────────────────────────────┤
│              │ ShopHealthCard (SPS / AHR bars)     │
└──────────────┴────────────────────────────────────┘
```

**Mobile:** single column — shop info may appear in header (`ShopInfoHeader`) with report
and health stacked.

**Báo cáo hôm nay domains** (current `REPORT_DOMAIN_IDS`):

| Domain ID | Vietnamese label | Content |
|-----------|------------------|---------|
| `revenue_growth` | Tăng trưởng | Revenue/ROAS-style metrics, sparklines |
| `product_listings` | Sản phẩm | Listing performance metrics |
| `inventory_refunds` | Tồn kho & Hoàn tiền | Inventory + refund signals |

Default tab resolves from `shop_profile` via `resolveDefaultReportDomain`.

**Metric tile interactions:**

- Tap → expand **Gợi ý từ Juli** (`--info` icon)
- CTA / estimated bar → `/decisions?highlight=<workflow_id>`
- Inbound `?highlight=<domain>:<metric>` → auto tab + scroll + pulse

**Shop Health:**

- `ShopHealthCard` with `HealthMetricBar` — 5-segment pink ramp, threshold ticks
- SPS, AHR, VP-style indicators with estimated affordance

**Not on this screen:** decision preview cards, Tiến độ, task queue, persona switcher,
approve/dismiss CTAs.

**Test IDs:** `seller-home-shell`, `seller-home-grid`, `todays-report-panel`,
`shop-health-card`.

---

### `/decisions` — Quyết định

| Attribute | Detail |
|-----------|--------|
| Component | `DecisionsPage` |
| Shell title | Quyết định |
| User question | What should I do? |
| Sub-tabs | `DecisionsSubTabs` |

**Sub-tab: Recommended (default)**

- `OperationsApprovalShell` — full ranked `ClarityCard` list
- Expand reasoning (`ReasoningPanel`)
- Approve / reject via `ApprovalGate`
- Inbound highlight: `?highlight=<workflow_id>` → scroll + 2s ring on matching card
- Test ID: `decisions-recommended-shell`

**Sub-tab: In Progress**

- `DecisionsInProgressShell` — statuses: `needs_input`, `executing`, `completed`

**Sub-tab: Workflow Templates**

- `DecisionsWorkflowTemplatesShell` — thresholds, automation (advanced)

---

### `/decisions/[decisionId]` — Decision detail

| Attribute | Detail |
|-----------|--------|
| Component | `DecisionDetailPage` → `DecisionDetailFlow` |
| Flow | 5-step guided sequence |
| Steps | Why → Analytics → Inputs → Preview → Approve |
| UI | `DecisionDetailStepIndicator` + step content |
| Actions | Back/next, approve → `TaskExecutorModals`, dismiss modal |
| Home link | Anticipation step → **Xem trên Trang chủ →** when anchor exists |

---

### `/ai-chat` — Juli AI

| Attribute | Detail |
|-----------|--------|
| Component | `AiChatPage` |
| Shell | `AuthenticatedShell` with `stickyFooter` for `ChatInput` |
| Content | `ChatMessageList`, `SuggestedPrompts` |
| Behavior | Mode-aware prompts; mock replies in pre-MVP |
| Context | Active decision persisted for contextual prompts |

---

## Affiliate workspace

When `juli_workspace_mode === "affiliate"`:

- `html.dark` applied
- Every authenticated route shows `AffiliateOutOfScope` (Vietnamese message)
- Dark theme per ADR-007 affiliate mapping

---

## Legacy redirects

Per ADR-007, deprecated routes 301 to canonical destinations (`legacy-redirects.js`):

| Legacy | Destination |
|--------|-------------|
| `/recommendations` | `/decisions` |
| `/creators`, `/orders`, etc. | Canonical seller routes or Home |

Component: `LegacyRouteRedirect`.

---

## Workflow modals (overlay — not routes)

Opened from Decisions approval / task executor:

| Workflow | Panel | Executable in P1.8 |
|----------|-------|-------------------|
| NPL | `ListingWorkflowPanel` | Yes (mock export) |
| Refund Spike (+ sub-journeys) | `LeakageWorkflowPanel` + `EvidenceDrawer` | Yes (mock) |
| Minimize Violations, Budget Optimization, Product Scaling, Stockout Prevention | Card + reasoning | Approve = no-op |

Modals: `TaskExecutorModals`, `TaskDismissModal` (skip with reason).

---

## Demo / dev surfaces

| Surface | Route / trigger | Purpose |
|---------|-----------------|---------|
| `DemoControlsDrawer` | Dev/demo controls | Persona and fixture switching |
| `PersonaSwitcher` | Not on Home IA | Legacy/demo persona selection |

---

## iOS (`ios/`) — reference only

Separate SwiftUI app; not primary OpenDesign scope for web baseline:

| Screen | File |
|--------|------|
| Login | `LoginView.swift` |
| Home | `HomeView.swift` |
| Daily loop | `DailyLoopView.swift`, `MorningSummaryView.swift`, etc. |

Web seller Decision Copilot IA is ahead of iOS seller parity.

---

## Visual layer target (Phase 2+)

Future Home KPI rendering expands per [`docs/visual_layer.md`](../visual_layer.md) —
six categories (Shop Status, Revenue, Ads, Inventory, Operations, Customer Service)
with chart types (forecast bands, gauges, rankings) and one-line advisory signals.
Current pre-MVP Home uses three Báo cáo domains + Shop Health as the shipped surface.

---

## Screen → component map

| Route | Primary components |
|-------|-------------------|
| `/` | `SellerHomeShell`, `HomeSummaryShell`, `TodaysReportPanel`, `ShopHealthCard`, `ShopInfoCard` |
| `/decisions` | `DecisionsPage`, `DecisionsSubTabs`, `OperationsApprovalShell`, `ClarityCard` |
| `/decisions/[id]` | `DecisionDetailFlow`, `ReasoningPanel`, `TaskExecutorModals` |
| `/ai-chat` | `AiChatPage`, `ChatMessageList`, `ChatInput`, `SuggestedPrompts` |
| `/login` | `LoginForm` |

## OpenDesign polish checklist per screen

| Screen | Focus areas |
|--------|-------------|
| Home | Grid balance, chart legibility, suggestion accordion, estimated glow, domain tab scroll |
| Decisions | Card hierarchy, impact prominence, reasoning expand, highlight ring |
| Decision detail | Step progress clarity, input forms, preview risks |
| Chat | Sticky input, prompt chips, message bubbles |
| Login | Form states, brand moment, error recovery |
