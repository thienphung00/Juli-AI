# PRD: Phase 2.6 — Demo Frontend (Mock Data)

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) Phase 2.6 brief ·
> [ADR-023](../../../adr/023-four-destination-analytics-ownership.md) (four-destination IA) ·
> [ADR-024](../../../adr/024-phase-2.6-2.7-frontend-resequencing.md) (this phase's split +
> mock/sign-in toggle) ·
> [ADR-026](../../../adr/026-phase-2.6-analytics-optional-exit-gate.md) (Analytics
> non-blocking exit gate, mirrors Settings/#405) ·
> [`docs/product/design/`](../../design/README.md) (design authority).
>
> **Revision note (2026-07-16, grill-with-docs):** this revision resolves 11 gaps found
> during a spec-readiness review — Analytics de-scoping (ADR-026), Sign-in interaction
> mechanics, exact breakpoints (now in `design.md`), fixture-contract location
> (`packages/contracts`), `packages/ui` build order, and several wording corrections. See
> `Further Notes` for the full list.

## Problem Statement

Juli needs a public-facing Interactive Demo that lets a visitor experience the real
product shape — Home, Decisions, Analytics, Settings — without waiting on backend
integration or authentication work. Today, no Demo frontend exists, and the
only written Demo spec (`phase-3-landing-demo.md`'s two-screen Home+Actions IA) conflicts
with the newer, canonical `docs/product/design` four-destination IA (ADR-023). Building
frontend and backend wiring together in one phase also makes the frontend hard to review
and ship independently.

## Solution

Build `apps/demo` as a new, standalone Next.js product implementing the ADR-023
four-destination IA on mock/hardcoded data only — reviewable and demoable on its own,
before any backend or authentication work. Ship it as one responsive codebase covering
both web and mobile-web breakpoints, publicly reachable over HTTPS at
`demo.app-juli.com`. Include a Mock/Sign-in mode toggle in the UI so Phase 3
can enable real data behind an existing seam, without redesigning IA under deployment
pressure — the Sign-in entry point exists now but is disabled.

## User Stories

1. As a visitor, I want to open the Demo and land on a sparse Home with exactly two
   destination cards (Decisions, Analytics), so that I immediately understand where to
   go without dashboard clutter.
2. As a visitor, I want Decisions to show Workflow 1 as the default Priority Card and
   every remaining mock workflow below it in a stable simple order, with reasoning,
   expected impact, and confidence, so that I understand why each suggestion exists
   without implying live ranking calculations.
3. As a visitor, I want to Approve a recommendation and see a prefilled/fillable workflow
   before anything executes, so that I understand Juli never acts without my decision.
4. As a visitor, I want to Reject a recommendation and see it removed immediately, so that
   I trust rejection is respected — final for the rest of the session until I explicitly
   trigger Manual Refresh, which is the Demo's only reset path.
5. As a visitor, I want to Expand a recommendation and see reasoning, evidence, impact,
   confidence, and risks, so that I can evaluate it before deciding.
6. As a visitor, I want to see approved work move into In Progress with
   `needs_input`/`executing`/`completed` states, so that I understand execution is
   tracked, not silent.
7. As a visitor, I want Analytics to show all six Main KPIs (SPS, Net Revenue, ROAS,
   Inventory Turnover, Fulfillment Accuracy Rate, CSAT) as one hero plus five selector
   cards, with comparisons, forecasts, and provenance per `Screens/analytics.md`, so
   that I can explore shop performance evidence. **Full delivery is a non-blocking
   stretch goal (#404, [ADR-026](../../../adr/026-phase-2.6-analytics-optional-exit-gate.md))**
   — a truthful placeholder is sufficient for the Phase 2.6 exit gate, mirroring Settings
   (story 8, #405).
8. As a visitor, I want Settings to show workflow templates and thresholds separately
   from Decisions, so that configuration and active work don't get confused.
9. As a visitor, I want Juli's contextual assistance to appear inside the active
   destination (never as a separate tab), so that help feels grounded, not bolted on.
10. As a visitor on a phone, I want the same information architecture, terminology, and
    approval behavior as on desktop — only layout adapting to the smaller viewport (below
    `42rem`/672px mobile-web, `56rem`/896px+ web, per `design.md`'s breakpoint table) — so
    that the product feels consistent across devices.
11. As a visitor, I want to see a Mock/Sign-in toggle, so that I understand the Demo can
    later connect to my own real data (even though Sign-in is disabled today).
12. As a visitor looking at the disabled Sign-in entry point, I want its "coming soon"
    explanation always visible next to it — not hidden behind a tap on a control that is
    itself non-functional — so that I'm not confused about what's available. Focusing or
    activating the control (keyboard or touch) re-announces the same text via an
    accessible live region; it never performs a route, dialog, or network action.
13. As a visitor, I want all copy in Vietnamese with correct diacritics and Juli's warm,
    direct voice, so that the product feels native and on-brand.
14. As a product/design reviewer, I want the Demo built from `docs/product/design`'s
    reusable component specs (not one-off styling), so that visual/interaction
    consistency is enforced by construction, not review.
15. As an engineer building `apps/landing` (Phase 2.7) or rebuilding `apps/dashboard`
    (Phase 3.5), I want shared UI/theme primitives already extracted into
    `packages/ui`/`packages/theme`, so that I don't re-derive the same tokens/components.
16. As a visitor with `prefers-reduced-motion` set, I want all Demo motion (card entry,
    approval feedback, loading, route change) to respect that preference.
17. As a visitor, I want every interactive element to meet a 44×44px minimum touch target
    with a visible focus-visible state, so that the Demo is usable via keyboard/touch.
18. As a visitor encountering an empty or loading state (e.g. Analytics before data
    "arrives" in the mock timeline), I want a truthful explanation of why and what happens
    next, so that I'm not confused by a blank screen.
19. As a visitor, I want to open `https://demo.app-juli.com` without authentication and
    receive the Demo over valid HTTPS, so that the Phase 2.6 experience is publicly
    reviewable on its intended domain.
20. As a visitor, I want a Manual Refresh action in the top corner on every destination
    that resets all mock state and returns me to the default Decisions Recommendations
    view, so that I can restart the Demo reliably.

## Implementation Decisions

- **New app:** `apps/demo` — Next.js (App Router), TypeScript, Tailwind, matching the
  stack already used in `apps/dashboard`. One responsive codebase; no separate
  mobile-web build. Deploy target in this phase: `demo.app-juli.com`.
- **Public deployment:** extend the existing Phase 2.5 VPS/Nginx/HTTPS deployment
  topology with an independently buildable and restartable Demo service. DNS must point
  `demo.app-juli.com` at the public host, Nginx must terminate TLS and proxy to the Demo,
  and deployment must not require backend credentials or API availability because Mock
  mode is self-contained.
- **IA source of truth:** `docs/product/design/` root authorities
  (`design-context.md` → `design.md` → `flows.md` → `soul.md` → `ux_principles.md`;
  EN→VI terms in repo-root `dictionary.md`), then
  `Screens/` (`home.md`, `decisions.md`, `analytics.md`, `settings.md`) and `Flows/`,
  then `Components/` + `colors_and_type.css`. Follow the
  `.cursor/skills/standalone/open-design-system/SKILL.md` loading sequence.
  **Explicitly excluded from this instruction** (Phase 3/3.5 scope, not Phase 2.6):
  `Flows/home/login.md`, `Flows/home/onboarding.md`, and any Affiliate/Seller
  ModeSwitcher content in `design.md`/`Components/navigation.md` — these describe real
  authentication and multi-tenant flows this phase does not build.
- **Breakpoints:** exact values live in `design.md`'s "Spacing, layout, and elevation"
  table — mobile-web below `42rem` (672px), web at/above `56rem` (896px), with the
  `42`–`56rem` band using mobile-web layout behavior. These are the same two values
  already shipped in `apps/demo/src/app/globals.css`, now promoted into the design
  authority.
- **Mock data layer:** hardcoded/fixture data module inside `apps/demo` (no requests to
  `backend/`, TikTok, or OAuth endpoints — asset/font requests are fine). Fixture types
  live in a new shared `packages/contracts` package (Decision/Action Card, execution,
  and KPI shapes), hand-kept structurally aligned with `docs/api/data-models/` — not
  code-generated from it — so Phase 3's swap to a live API client is a data-source
  change, not a type rewrite.
- **Mock/Sign-in toggle:** a persisted UI mode (mirroring the existing
  `NEXT_PUBLIC_UI_ONLY`-style pattern in `apps/dashboard`) with two states —
  `mock` (default) and `signin`. In this phase `signin` is a non-interactive,
  `aria-disabled` option with an always-visible inline "Sắp có" (coming soon) caption
  next to it (not hidden behind a tap). It stays keyboard-focusable for discoverability;
  activating it (click/Enter/Space) is a no-op that re-announces the same caption via an
  `aria-live` region — never a route, dialog, OAuth redirect, or backend call.
- **Mock recommendation ordering:** Workflow 1 (`create_hero_product_1`) is the default
  Priority Card. Workflows 2–9 all remain visible in the same Recommendations tab below
  it in stable specification order. Phase 2.6 performs no ranking calculation.
- **Manual Refresh:** a global top-corner action is available from every destination. It
  clears mutable mock state (rejections, approvals, workflow inputs, execution progress,
  Analytics selection/range, and unsaved Settings edits) and navigates to the default
  `/decisions` Recommendations view.
- **Shared packages, atomic-design build order:** `packages/ui`'s full named inventory
  (buttons, cards, badges, dialogs, forms, tables, health bars, progress bars, toasts,
  loading indicators, popovers, navigation, chips, charts — per `Components/`) is built
  **element/primitive first, then composition, before the combined `apps/demo` screens
  that consume them** — reversing the incremental "extract as a screen needs it"
  approach #397 shipped. Split into small per-category issues (e.g. core elements;
  surface compositions; feedback + navigation compositions) that block #400 and #404, so
  the library exists before the screens that render it. `packages/theme` (tokens from
  `colors_and_type.css`, Tailwind preset) follows the same import-boundary rules in
  `architecture/migration-plan.md` (`apps/* → packages/*`, never `apps/* → apps/*`).
  `apps/demo` consumes these packages rather than duplicating component code. **Exit-gate
  scope:** the gate checks only the subset of the full inventory actually consumed by a
  shipped `apps/demo` screen — an unused primitive (e.g. a table with no consuming
  screen yet) does not block sign-off even though it was built element-first.
- **Charts:** Analytics charts use Recharts (existing convention in `apps/dashboard`),
  series colors from CSS variables, keyboard-accessible.
- **Formatting:** currency via `formatVND`, dates via `formatDate`/`formatDateTime`
  (ICT), impact values via `formatNumber` — reuse existing formatting utilities rather
  than reintroducing them (extract into `packages/utils` if not already shared).
- **Analytics/telemetry:** defer PostHog wiring to Phase 3; the Phase 2.6 public
  deployment ships without behavior analytics.

## Testing Decisions

- Component/unit tests per new `packages/ui` primitive (render + interaction states:
  default, hover, pressed, focus-visible, disabled, loading, error, empty) — mirrors the
  interactive state contract in `design.md`.
- Integration tests per destination: Home renders exactly two cards and links correctly;
  Decisions Approve/Reject/Expand behavior on mock data across all nine workflows;
  Settings surfaces templates/thresholds only. Analytics integration tests apply only if
  #404 ships (non-blocking per ADR-026); otherwise the truthful-placeholder state is
  tested instead.
- A snapshot/regression test asserting the Mock/Sign-in toggle defaults to `mock`, that
  `signin`'s "coming soon" caption is visible without interaction, and that activating
  the control makes no route/OAuth/backend/network call.
- A deterministic ordering test asserting Workflow 1 is the Priority Card and Workflows
  2–9 render below it in stable specification order without a ranking calculation.
- A Manual Refresh integration test starting from mutated state in each destination,
  then asserting all mock state resets and `/decisions` opens on Recommendations. The
  Settings-edit portion of this test only runs if #405 ships; it is not required for
  exit.
- Playwright responsive/E2E suites for the two canonical breakpoints (mobile-web below
  `42rem`, web at/above `56rem`, per `design.md`) verifying identical IA/terminology
  across the Decisions journey (Home → Decisions → recommendation review → In Progress),
  per `flows.md` platform parity. `apps/demo`'s existing Vitest/jsdom suite cannot verify
  real layout/reflow and is not sufficient on its own for this requirement.
- Production-build and deploy-contract tests proving `apps/demo` can be built and served
  independently, without requests to `backend/`, TikTok, or OAuth endpoints (asset/font
  requests are expected and allowed).
- A public smoke check verifies DNS resolution, a valid HTTPS certificate, a 2xx response
  from `https://demo.app-juli.com`, and successful loading of the Decisions route (the
  minimum mandatory route) on both desktop and mobile-web viewports. Analytics/Settings
  routes are checked only if shipped.
- Follow existing test layout conventions in `apps/dashboard/src/__tests__/` for test
  structure and naming.

## Exit Gate

- `apps/demo` implements Home and Decisions (all nine workflows) per
  `docs/product/design/` on mock data, with a four-destination shell that keeps
  Analytics and Settings discoverable. **Decisions is the only destination with
  mandatory detail routes** (`/decisions`, `/decisions/recommendations/[id]`,
  `/decisions/in-progress/[id]`) — Analytics' and Settings' detail routes inherit their
  parent issues' optional status below.
- Mock mode is fully interactive with no auth required. Sign-in mode is present as a
  non-interactive, always-visible "coming soon" stub (no route/OAuth/backend call on
  activation) — see Implementation Decisions.
- Web (`56rem`/896px+) and mobile-web (below `42rem`/672px) breakpoints, as defined in
  `design.md`, are verified via Playwright for the mandatory Decisions journey.
- `packages/ui` and `packages/theme` are populated, element/composition-first, with at
  least every primitive consumed by a shipped Home/Decisions screen; `packages/contracts`
  holds the typed mock-data fixtures consumed by `apps/demo`.
- `https://demo.app-juli.com` publicly resolves, serves `apps/demo` over valid HTTPS,
  and passes desktop + mobile-web smoke checks on the Decisions route without backend
  dependencies.

**Non-blocking Phase 2.6 stretch goals** (truthful placeholder sufficient for exit;
failure or deferral does not block sign-off):

- Full editable Settings templates/thresholds (#405, story 8).
- Full six-KPI Analytics experience (#404, story 7,
  [ADR-026](../../../adr/026-phase-2.6-analytics-optional-exit-gate.md)) — Home's
  Analytics launcher card (ADR-023) always renders regardless of this stretch's status.

## Out of Scope

- Any real backend/API calls, real TikTok OAuth, or real data (Phase 3).
- Real authentication, session recovery, or onboarding flows (`Flows/home/login.md`,
  `Flows/home/onboarding.md`) and Affiliate/Seller mode switching — Phase 3/3.5 scope,
  not read from `docs/product/design/` for this phase despite being in that package.
- Landing Page build (Phase 2.7 — separate PRD).
- Rebuilding `apps/dashboard` itself (Phase 3.5).
- Multi-tenant account/session management, per-visitor shop connection (Phase 3.5).
- PostHog/behavior analytics instrumentation (Phase 3).
- Native mobile app (`apps/mobile`, Phase 4+).

## Further Notes

- **Risk:** duplicating IA work between `apps/demo` and the eventual `apps/dashboard`
  ADR-023 rebuild (Phase 3.5) if `packages/ui`/`packages/theme` extraction lags behind —
  mitigated by building the full component inventory element/composition-first (see
  Implementation Decisions), ahead of the screens that consume it.
- **Follow-up:** `architecture/migration-plan.md`'s PR sequence (`3-a` scaffold
  apps/landing+demo, `3.5-a` extract packages/ui) predates this PRD and should be
  renumbered against Phase 2.6/2.7/3 in a follow-up pass (tracked, not blocking this PRD).
- **Rollout:** `apps/demo` becomes publicly reachable in Phase 2.6, but remains a
  self-contained mock experience with no authentication, seller data, backend dependency,
  or production write path. Rollback must restore the previous healthy Demo release
  without affecting `app-juli.com` or `api.app-juli.com`.
- **Grill trail (2026-07-16):** this revision resolved, in order: (1) Analytics
  non-blocking exit gate — [ADR-026](../../../adr/026-phase-2.6-analytics-optional-exit-gate.md);
  (2) Sign-in disabled-but-explanatory interaction mechanics; (3) exact breakpoint values,
  promoted into `design.md`; (4) "no network calls" wording scoped to
  backend/TikTok/OAuth; (5) explicit exclusion of login/onboarding/Affiliate content from
  the design-source instruction; (6) `packages/ui` atomic-design build order with
  consumed-subset exit-gate scope; (7) fixture contracts moved to a new
  `packages/contracts` package; (8) Playwright adopted for responsive/E2E verification;
  (9) Decisions-only mandatory detail routes; (10) "rejection is final" clarified against
  Manual Refresh; (11) contextual-assistance acceptance criteria confirmed already
  covered by #398/#404/#405/#407's existing "Contextual assistance"/"Assistance
  regression" bullets — no PRD gap remained there once the issue tracker was checked.
