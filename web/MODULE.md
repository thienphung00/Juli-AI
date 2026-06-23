# Module: web

## Responsibility
Next.js web dashboard for the Juli platform. Provides Vietnamese-language UI
for TikTok Shop sellers: phone-OTP login, homepage with GMV/livestream/AI
modules, orders management with filtering and shipment confirmation.

## Public Interface
- `SellerHomeShell`, `PersonaSwitcher` — Phase 1 seller entry: read-only home summary (health hero + top-3 decision preview) + demo persona switcher; approval pipeline lives on `/decisions` (`components/seller-home/`, `components/workflows/operations/`)
- `resolveSellerWorkflow`, `getWorkflowTasks`, `WORKFLOW_ENTRIES` — rules-based workflow routing from mock personas (`lib/seller-workflows.ts`)
- `DemoPersonaProvider`, `useDemoPersona` — persisted demo persona selection (`lib/demo-persona-context.tsx`)
- `TaskCard`, `TaskQueue`, `DemoModeNotice` — Phase 1 shared task UI + no-op approve/dismiss (`components/tasks/`)
- `NewSellerCopilotPanel`, `MilestoneProgress` — New-seller workflow checklist + first-sale milestone bar (`components/workflows/new-seller/`)
- `computeFirstSaleMilestone` — Pure milestone % from mock profile orders/GMV (`lib/workflows/new-seller/milestone.ts`)
- `LeakageCopilotPanel`, `LeakageWorkflowPanel`, `EvidenceDrawer`, `resolveEvidence` — Phase 1 revenue leakage workflow: ranked anomalies, modal executable workflow, masked evidence drill-down (`components/workflows/leakage/`, `lib/workflows/leakage/`)
- `GrowthCopilotPanel`, `AdPerformanceSummary`, `computeAdSummary`, `rankGrowthTasks` — Phase 1 growth workflow: ad performance summary + ranked scale/cut recommendations (`components/workflows/growth/`, `lib/workflows/growth/`)
- `useTaskExecutor`, `filterActiveTasks`, `TaskDismissModal`, `TaskExecutorModals`, session helpers — client-only task queue state + global skip-with-reason (`lib/task-executor/`, `components/tasks/`)
- `trackTaskClicked`, `trackTaskApproved`, `trackTaskDismissed`, `getUxSessionId` — Phase 1 UX instrumentation sink (`lib/ux-analytics/`)
- `/login` — Phone-OTP login screen (Vietnamese phone format)
- `/mode-select` — Post-login workspace gate (Seller vs Affiliate); skipped when mode is persisted
- `/` — Seller home shell (workflow breadcrumb + persona tasks); canonical seller entry (#118, #123)
- `toDecision`, `takeTopDecisions`, `applyDecisionLifecycle` — Decision view-model mapping `workflow_recommendations` → seller-facing Decision envelopes (`lib/decisions/`, #192)
- `/decisions` — Decisions tab: Recommended / In Progress / Workflow Templates sub-tabs; approval gate + full ranked list on Recommended (#195); mock per-workflow template settings (#198); ADR-028 3-tab IA (#191)
- `/decisions/[decisionId]` — Guided 5-step decision detail flow (why → analytics → inputs → preview → approve) (#196)
- `/creators` — Legacy creator-matching; 301 → `/` (#123)
- `/recommendations` — Legacy decision feed; 301 → `/decisions` (#191)
- `/ai-chat` — Juli AI chat tab (mode-aware suggested prompts, mock replies in UI-only)
- `/alerts` — Legacy; 301 → `/` (alerts in header drawer only)
- `/orders` — Legacy; 301 → `/operation` → `/`
- `/products` — Legacy; 301 → `/trends` → `/`
- `/inventory` — Legacy; 301 → `/operation` → `/`
- `/livestreams`, `/trends`, `/operation` — Legacy seller-OS routes; 301 → `/` (retired from bottom nav, issue #95)

## Dependencies
- `api` (read-only) — consumes `GET /v1/shops`, `GET /v1/shops/me`, orders endpoints
- `auth` (read-only) — login uses Supabase phone-OTP flow via API endpoints (not direct Supabase client calls from browser)

## Stack
- Next.js 14 (App Router)
- TypeScript
- Tailwind CSS
- Vietnamese locale (VND ₫ formatting, diacritics, ICT timezone)

## Bottom navigation (ADR-028, #191)
Seller workspace exposes exactly **3** fixed tabs via `BOTTOM_NAV_TABS` in `lib/nav-config.ts`:

| Tab | Route | Label |
|-----|-------|-------|
| Home | `/` | Trang chủ |
| Decisions | `/decisions` | Quyết định |
| Juli AI | `/ai-chat` | Juli |

Touch targets: minimum 44×44px per `NavBar`. Active state via `isNavTabActive(pathname, href)`.

## Invariants
- Workspace mode (`seller` | `affiliate`) is persisted in `localStorage` (`juli_workspace_mode`) and drives the `dark` class on `<html>` (Seller=light white canvas, Affiliate=dark; ADR-027/#191)
- Phase 1: Affiliate mode shows a Vietnamese out-of-scope state on every authenticated route via `AuthenticatedShell`; Seller mode renders workflow UI
- Auth MUST go through the API layer — no direct Supabase client calls from the browser
- All UI text in Vietnamese with proper diacritics
- Currency formatted as VND (₫) with thousands separators
- Mobile-responsive with single-thumb operation patterns
- Empty states rendered gracefully when API returns no data
- Pages load within 2 seconds (measured via Core Web Vitals)

## Owners
- domain: web
- code: web/
