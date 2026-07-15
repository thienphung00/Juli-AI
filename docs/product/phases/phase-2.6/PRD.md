# PRD: Phase 2.6 — Demo Frontend (Mock Data)

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) Phase 2.6 brief ·
> [ADR-023](../../../adr/023-four-destination-analytics-ownership.md) (four-destination IA) ·
> [ADR-024](../../../adr/024-phase-2.6-2.7-frontend-resequencing.md) (this phase's split +
> mock/sign-in toggle) · [`docs/product/design/`](../../design/README.md) (design authority).

## Problem Statement

Juli needs a public-facing Interactive Demo that lets a visitor experience the real
product shape — Home, Decisions, Analytics, Settings — without waiting on backend
integration, deployment, or authentication work. Today, no Demo frontend exists, and the
only written Demo spec (`phase-3-landing-demo.md`'s two-screen Home+Actions IA) conflicts
with the newer, canonical `docs/product/design` four-destination IA (ADR-023). Building
frontend and backend wiring together in one phase also makes the frontend hard to review
and ship independently.

## Solution

Build `apps/demo` as a new, standalone Next.js product implementing the ADR-023
four-destination IA on mock/hardcoded data only — reviewable and demoable on its own,
before any backend or deployment work. Ship it as one responsive codebase covering both
web and mobile-web breakpoints. Include a Mock/Sign-in mode toggle in the UI so Phase 3
can enable real data behind an existing seam, without redesigning IA under deployment
pressure — the Sign-in entry point exists now but is disabled.

## User Stories

1. As a visitor, I want to open the Demo and land on a sparse Home with exactly two
   destination cards (Decisions, Analytics), so that I immediately understand where to
   go without dashboard clutter.
2. As a visitor, I want Decisions to show ranked recommendation cards with reasoning,
   expected impact, and confidence, so that I understand why each suggestion exists.
3. As a visitor, I want to Approve a recommendation and see a prefilled/fillable workflow
   before anything executes, so that I understand Juli never acts without my decision.
4. As a visitor, I want to Reject a recommendation and see it removed immediately, so that
   I trust rejection is respected and final.
5. As a visitor, I want to Expand a recommendation and see reasoning, evidence, impact,
   confidence, and risks, so that I can evaluate it before deciding.
6. As a visitor, I want to see approved work move into In Progress with
   `needs_input`/`executing`/`completed` states, so that I understand execution is
   tracked, not silent.
7. As a visitor, I want Analytics to show all KPIs, comparisons, forecasts, and reports —
   including the six Main KPIs (SPS, Net Revenue, ROAS, Inventory Turnover, Fulfillment
   Accuracy Rate, CSAT) — so that I can explore shop performance evidence.
8. As a visitor, I want Settings to show workflow templates and thresholds separately
   from Decisions, so that configuration and active work don't get confused.
9. As a visitor, I want Juli's contextual assistance to appear inside the active
   destination (never as a separate tab), so that help feels grounded, not bolted on.
10. As a visitor on a phone, I want the same information architecture, terminology, and
    approval behavior as on desktop — only layout adapting to the smaller viewport — so
    that the product feels consistent across devices.
11. As a visitor, I want to see a Mock/Sign-in toggle, so that I understand the Demo can
    later connect to my own real data (even though Sign-in is disabled today).
12. As a visitor tapping the disabled Sign-in entry point, I want a clear "coming soon"
    state (not a broken link or silent no-op), so that I'm not confused about what's
    available.
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

## Implementation Decisions

- **New app:** `apps/demo` — Next.js (App Router), TypeScript, Tailwind, matching the
  stack already used in `apps/dashboard`. One responsive codebase; no separate
  mobile-web build. Deploy target (Phase 3): `demo.app-juli.com`.
- **IA source of truth:** `docs/product/design/` root authorities
  (`context.md` → `design.md` → `flows.md` → `soul.md` → `ux_principles.md`), then
  `Screens/` (`home.md`, `decisions.md`, `analytics.md`, `settings.md`) and `Flows/`,
  then `Components/` + `colors_and_type.css`. Follow the
  `.cursor/skills/standalone/open-design-system/SKILL.md` loading sequence.
- **Mock data layer:** hardcoded/fixture data module inside `apps/demo` (no network
  calls to `backend/`). Shape mock objects to match the real Decision/Action Card and
  KPI contracts documented in `data-models/` so Phase 3's swap to a live API client is a
  data-source change, not a UI rewrite.
- **Mock/Sign-in toggle:** a persisted UI mode (mirroring the existing
  `NEXT_PUBLIC_UI_ONLY`-style pattern in `apps/dashboard`) with two states —
  `mock` (default) and `signin` (disabled entry point in this phase; renders a
  "coming soon" state, no route, no OAuth redirect, no backend call).
- **Shared packages:** begin populating `packages/ui` (buttons, cards, badges, dialogs,
  forms, tables, health bars, progress bars, toasts, loading indicators, popovers,
  navigation, chips, charts — per `Components/`) and `packages/theme` (tokens from
  `colors_and_type.css`, Tailwind preset) per the import boundary rules in
  `architecture/migration-plan.md` (`apps/* → packages/*`, never `apps/* → apps/*`).
  `apps/demo` consumes these packages rather than duplicating component code.
- **Charts:** Analytics charts use Recharts (existing convention in `apps/dashboard`),
  series colors from CSS variables, keyboard-accessible.
- **Formatting:** currency via `formatVND`, dates via `formatDate`/`formatDateTime`
  (ICT), impact values via `formatNumber` — reuse existing formatting utilities rather
  than reintroducing them (extract into `packages/utils` if not already shared).
- **Analytics/telemetry:** defer PostHog wiring to Phase 3 (real deployment); Phase 2.6
  ships UI only.

## Testing Decisions

- Component/unit tests per new `packages/ui` primitive (render + interaction states:
  default, hover, pressed, focus-visible, disabled, loading, error, empty) — mirrors the
  interactive state contract in `design.md`.
- Integration tests per destination: Home renders exactly two cards and links correctly;
  Decisions Approve/Reject/Expand behavior on mock data; Analytics renders all six Main
  KPIs with correct hero/selector layout; Settings surfaces templates/thresholds only.
- A snapshot/regression test asserting the Mock/Sign-in toggle defaults to `mock` and
  that selecting `signin` renders the disabled/"coming soon" state without a network call
  or route change.
- Responsive tests (or Storybook/viewport stories) verifying the two required breakpoints
  (web, mobile-web) preserve identical IA/terminology, per `flows.md` platform parity.
- Follow existing test layout conventions in `apps/dashboard/src/__tests__/` for test
  structure and naming.

## Out of Scope

- Any real backend/API calls, real TikTok OAuth, or real data (Phase 3).
- Public deployment/DNS/HTTPS for `demo.app-juli.com` (Phase 3).
- Landing Page build (Phase 2.7 — separate PRD).
- Rebuilding `apps/dashboard` itself (Phase 3.5).
- Multi-tenant account/session management, per-visitor shop connection (Phase 3.5).
- PostHog/behavior analytics instrumentation (Phase 3).
- Native mobile app (`apps/mobile`, Phase 4+).

## Further Notes

- **Risk:** duplicating IA work between `apps/demo` and the eventual `apps/dashboard`
  ADR-023 rebuild (Phase 3.5) if `packages/ui`/`packages/theme` extraction lags behind —
  mitigated by extracting shared components as they're built, not after.
- **Follow-up:** `architecture/migration-plan.md`'s PR sequence (`3-a` scaffold
  apps/landing+demo, `3.5-a` extract packages/ui) predates this PRD and should be
  renumbered against Phase 2.6/2.7/3 in a follow-up pass (tracked, not blocking this PRD).
- **Rollout:** no production users affected — `apps/demo` is unreachable publicly until
  Phase 3 deploys it.
