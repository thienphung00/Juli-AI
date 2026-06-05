# Module: web

## Responsibility
Next.js web dashboard for the Juli platform. Provides Vietnamese-language UI
for TikTok Shop sellers: phone-OTP login, homepage with GMV/livestream/AI
modules, orders management with filtering and shipment confirmation.

## Public Interface
- `SellerHomeShell`, `PersonaSwitcher` — Phase 1 seller entry: stage-routed workflow shell + demo persona switcher (`components/seller-home/`)
- `resolveSellerWorkflow`, `getWorkflowTasks`, `WORKFLOW_ENTRIES` — rules-based workflow routing from mock personas (`lib/seller-workflows.ts`)
- `DemoPersonaProvider`, `useDemoPersona` — persisted demo persona selection (`lib/demo-persona-context.tsx`)
- `TaskCard`, `TaskQueue`, `DemoModeNotice` — Phase 1 shared task UI + no-op approve/dismiss (`components/tasks/`)
- `NewSellerCopilotPanel`, `MilestoneProgress` — New-seller workflow checklist + first-sale milestone bar (`components/workflows/new-seller/`)
- `computeFirstSaleMilestone` — Pure milestone % from mock profile orders/GMV (`lib/workflows/new-seller/milestone.ts`)
- `LeakageCopilotPanel`, `EvidenceDrawer`, `resolveEvidence` — Phase 1 revenue leakage workflow: ranked anomalies, masked evidence drill-down (`components/workflows/leakage/`, `lib/workflows/leakage/`)
- `GrowthCopilotPanel`, `AdPerformanceSummary`, `computeAdSummary`, `rankGrowthTasks` — Phase 1 growth workflow: ad performance summary + ranked scale/cut recommendations (`components/workflows/growth/`, `lib/workflows/growth/`)
- `useTaskExecutor`, `filterActiveTasks`, session helpers — client-only task queue state (`lib/task-executor/`)
- `/login` — Phone-OTP login screen (Vietnamese phone format)
- `/mode-select` — Post-login workspace gate (Seller vs Affiliate); skipped when mode is persisted
- `/` — Seller home shell (workflow breadcrumb + persona tasks); legacy creator-matching KPIs retired from seller entry (#118)
- `/creators` — Creator GMV attribution and commission efficiency scorecards (primary nav)
- `/recommendations` — Decision feed: `MatchDecisionCard`, predicted outcomes, match score, CTA analytics
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

## Invariants
- Workspace mode (`seller` | `affiliate`) is persisted in `localStorage` (`juli_workspace_mode`) and drives the `dark` class on `<html>` (Seller=dark, Affiliate=light)
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
