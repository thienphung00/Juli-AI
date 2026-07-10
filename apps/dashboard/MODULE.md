# Module: web

## Responsibility
Next.js web dashboard for the Juli platform. Provides Vietnamese-language UI
for TikTok Shop sellers: **one-click demo login**, **interactive chart-first Home dashboard**,
Decisions approval flow, and Juli AI chat.

## Public Interface
- `SellerHomeShell`, `HomeSummaryShell` — Phase 1 seller Home: **shop info in header** + **Báo cáo hôm nay (chart dashboard) → Shop Health** in body; no task preview, Tiến độ, or demo persona switcher on Home (`components/seller-home/`, `components/workflows/operations/`, `components/home/todays-report/`)
- `ShopInfoHeader`, `ShopInfoCard` — shop name + status (`ShopInfoHeader` in `PageHeader`; card variant retained for tests/legacy)
- `TodaysReportPanel`, `ReportMetricChart`, `TodaysReportDomainCard` — tabbed metrics dashboard with Recharts sparklines, real/estimated bars, Juli suggestion expand, link to Decisions (`components/home/todays-report/`, `lib/operations/todays-report.ts`)
- `ShopHealthCard`, `HealthMetricBar` — SPS/AHR score bars with 5-segment pink ramp, threshold ticks, estimated affordance (`components/workflows/operations/`)
- `RealEstimatedBar`, `resolveMetricWorkflowId`, `buildDecisionsHighlightLink` — estimated-segment affordance + metric→Decisions navigation (`components/workflows/operations/`, `lib/operations/metric-action-mapping.ts`, `lib/operations/journey-loop.ts`)
- `DemoPersonaProvider`, `useDemoPersona` — persisted demo persona selection (`lib/demo-persona-context.tsx`)
- `TaskCard`, `TaskQueue`, `DemoModeNotice` — shared task UI on Decisions / modals (`components/tasks/`)
- `LeakageWorkflowPanel`, `EvidenceDrawer`, `resolveEvidence` — leakage workflow modal + masked evidence drill-down (`components/workflows/leakage/`, `lib/workflows/leakage/`)
- `useTaskExecutor`, `filterActiveTasks`, `TaskDismissModal`, `TaskExecutorModals` — client-only task queue state + skip-with-reason (`lib/task-executor/`, `components/tasks/`)
- `trackTaskClicked`, `trackTaskApproved`, `trackTaskDismissed`, `getUxSessionId` — Phase 1 UX instrumentation sink (`lib/ux-analytics/`)
- `/login` — Demo login screen (one-click entry)
- `/mode-select` — Post-login workspace gate (Seller vs Affiliate); skipped when mode is persisted
- `/` — **Chart-first Home** (shop info + Báo cáo hôm nay + Shop Health); canonical seller entry (#118, #123, #215 RRAA loop)
- `toDecision`, `takeTopDecisions`, `applyDecisionLifecycle` — Decision view-model mapping `workflow_recommendations` → seller-facing Decision envelopes (`lib/decisions/`, #192)
- `/decisions` — Decisions tab: Recommended / In Progress / Workflow Templates; approval gate; **"Xem trên Trang chủ →"** after Anticipation returns to Home (#195, #215)
- `/decisions/[decisionId]` — Guided 5-step decision detail flow (why → analytics → inputs → preview → approve) (#196)
- `/ai-chat` — Juli AI chat tab (mode-aware suggested prompts, mock replies in UI-only)
- Legacy routes (`/creators`, `/recommendations`, `/orders`, etc.) — 301 to canonical routes per ADR-014

## Home information architecture (Phase 1.8)

**Layout on `/`:**

- **Header:** `ShopInfoHeader` — shop name + status (replaces workflow copilot subtitle)
- **Body:** `TodaysReportPanel` then `ShopHealthCard`

**Not on Home:** top-3 decision preview, Tiến độ gần đây, workflow breadcrumb, persona copilot panels (`NewSellerCopilotPanel`, `LeakageCopilotPanel`, `GrowthCopilotPanel` retired from Home).

**Metric interaction:** tap tile → expand **Gợi ý từ Juli** (blue info icon); second action → `/decisions?highlight=<workflow_id>`. Estimated bar segment remains a secondary deep link to the same destination. RRAA is cross-screen logic only — **no stage labels in UI**.

## RRAA journey loop (P1.8-10, ADR-029)

Cross-screen **Reward → Reason → Action → Anticipation** loop between Home charts and Decisions cards. Registry and parsers live in `lib/operations/journey-loop.ts`; hooks in `use-journey-highlight.ts` (Decisions inbound) and `use-home-journey-highlight.ts` (Home inbound).

| Export / hook | Role |
|---------------|------|
| `getJourneyLink(workflowId)` | Registry row: Home metric anchor, Reason/Anticipation copy |
| `resolveJourneyLinkForMetric(domain, metricKey)` | Metric tile → workflow mapping (incl. overrides) |
| `buildDecisionsHighlightLink(workflowId)` | Outbound Home → `/decisions?highlight=<workflow_id>` |
| `buildHomeHighlightLink(anchor)` | Outbound Decisions → `/?highlight=<domain>:<metric>` |
| `parseDecisionsHighlight(param)` | Validates Decisions `?highlight=` (invalid → ignored) |
| `parseHomeHighlight(param)` | Parses Home `?highlight=<domain>:<metric>` |
| `useJourneyHighlight(workflowIds)` | Decisions: scroll + 2s ring on matching `ClarityCard` |
| `useHomeJourneyHighlight()` | Home: auto-select Báo cáo tab, scroll + pulse target metric/chart |

**Interaction model (growth example):** expand metric tile **Gợi ý từ Juli** → CTA to Decisions; or tap estimated bar → same `?highlight=`; on Decisions card, **Xem trên Trang chủ →** after Anticipation returns to Home with `/?highlight=revenue_growth:roas` (tab switch + chart highlight). Full loop covered by `test_issue221_rraa_loop.test.tsx`.

## Dependencies
- `api` (read-only) — consumes `GET /v1/shops`, `GET /v1/shops/me`, orders endpoints
- `auth` (read-only) — demo login stores a local session token (no backend auth call)

## Stack
- Next.js 16 (App Router)
- React 19
- TypeScript
- Tailwind CSS
- **Recharts** — Home metric sparklines / interactive charts
- Vietnamese locale (VND ₫ formatting, diacritics, ICT timezone)

## Decision object (ADR-014, #192)

Primary seller-facing UI object — one envelope per validated `workflow_id` (ADR-013 six-workflow catalog).

| Field | Source |
|-------|--------|
| `id` | `workflow_id` |
| `title` | `workflow_name` |
| `estimated_impact` | `expected_impact.metric` + `value` |
| `confidence` | `expected_impact.confidence` |
| `reasoning_summary` | `rationale` |
| `required_inputs` | Per-workflow mock catalog |
| `status` | `recommended` \| `needs_input` \| `executing` \| `completed` |

Mapping lives in `lib/decisions/`. **Decisions Recommended** shows the full ranked list; Home does not preview top N.

## White canvas invariant (ADR-014, #191)

Seller workspace (`html` without `.dark`):

- `--background`, `--header-background`, `--muted` → `#FFFFFF` (not pink tint `#FEF5F6`)
- Brand pink `#F86BA5` is accent-only (health bars, primary CTAs, Juli tab highlight)
- Affiliate workspace keeps dark canvas per ADR-015

## Bottom navigation (ADR-014, #191)
Seller workspace exposes exactly **3** fixed tabs via `BOTTOM_NAV_TABS` in `lib/nav-config.ts`:

| Tab | Route | Label |
|-----|-------|-------|
| Home | `/` | Trang chủ |
| Decisions | `/decisions` | Quyết định |
| Juli AI | `/ai-chat` | Juli |

Touch targets: minimum 44×44px per `NavBar`. Active state via `isNavTabActive(pathname, href)`.

## Invariants
- Workspace mode (`seller` | `affiliate`) is persisted in `localStorage` (`juli_workspace_mode`) and drives the `dark` class on `<html>` (Seller=light white canvas, Affiliate=dark; ADR-015/#191)
- Phase 1: Affiliate mode shows a Vietnamese out-of-scope state on every authenticated route via `AuthenticatedShell`; Seller mode renders chart dashboard Home
- Auth MUST go through the API layer — no direct Supabase client calls from the browser
- All UI text in Vietnamese with proper diacritics
- Currency formatted as VND (₫) with thousands separators
- Home: chart-first, minimal copy; Decisions: approve/dismiss + **"Xem trên Trang chủ →"** return link
- Mobile-responsive with single-thumb operation; desktop Home uses dashboard grid (not only `max-w-lg`)
- Empty states rendered gracefully when API returns no data
- Pages load within 2 seconds (measured via Core Web Vitals)
- Estimated-segment glow respects `prefers-reduced-motion`

## Owners
- domain: web
- code: apps/dashboard/
