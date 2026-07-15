# PRD: Phase 2.7 — Landing Frontend (Mock Data)

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) Phase 2.7 brief ·
> [ADR-024](../../../adr/024-phase-2.6-2.7-frontend-resequencing.md) (this phase's split +
> app boundaries) · [`docs/product/design/design.md`](../../design/design.md) and
> [`soul.md`](../../design/soul.md) (visual tokens + brand voice reused here only).

## Problem Statement

Juli has no public marketing site. Prospective sellers who hear about Juli have nowhere
to learn why it exists, what it does differently from a generic analytics dashboard, or
how to try it — before Phase 3 wires up a real backend and deploys anything publicly.
`docs/product/design` defines the app's IA (Home/Decisions/Analytics/Settings) but has no
landing-page spec, since a marketing site is a different product with different goals
(persuade and convert, not operate a shop).

## Solution

Build `apps/landing` as a new, standalone Next.js product with its own content and
information architecture — a marketing story, not an app screen — reusing
`docs/product/design`'s visual tokens (`design.md`) and brand voice (`soul.md`) for visual
and tonal consistency only. Ship it as one responsive codebase covering both web and
mobile-web breakpoints, on mock/static content, with a clear call-to-action into the
Demo (`apps/demo`, Phase 2.6).

## User Stories

1. As a prospective seller, I want a hero section that states in one line what Juli does
   and why it's different, so that I understand the value within seconds.
2. As a prospective seller, I want a short "why Juli exists" story section reinforcing
   the Observe → Understand → Recommend → Approve → Execute → Measure workflow, so that I
   understand Juli's approach before exploring features.
3. As a prospective seller, I want feature highlight sections (recommendations with
   reasoning, explicit approval gate, execution tracking, analytics evidence), so that I
   understand what I'll see if I try the Demo.
4. As a prospective seller, I want a clear, prominent CTA that takes me into the Demo
   (`apps/demo`, Mock mode), so that I can experience the product myself with no signup
   friction.
5. As a prospective seller, I want Juli's brand voice (warm, direct, "here's what I found,
   here's what it's worth, here's what I'd do — your call") reflected in the copy, so that
   the marketing site feels consistent with the product.
6. As a prospective seller on a phone, I want the same content and message — only layout
   adapting to the smaller viewport — so that the story doesn't change across devices.
7. As a prospective seller, I want the same visual tokens (brand pink accent, Inter
   typography, spacing/elevation) as the product itself, so that the marketing site
   doesn't feel like a different, disconnected product.
8. As a visitor with `prefers-reduced-motion` set, I want landing-page motion (hero
   entry, scroll reveals) to respect that preference.
9. As a visitor, I want every interactive element (CTA buttons, nav links) to meet a
   44×44px minimum touch target with a visible focus-visible state.
10. As a product/design reviewer, I want the landing page built from the same
    `packages/ui`/`packages/theme` primitives as `apps/demo` (Phase 2.6) wherever a
    reusable component applies (buttons, cards, badges), so that visual drift between
    the two public-facing surfaces doesn't accumulate.
11. As a marketer, I want the page structured so that later real content (screenshots,
    testimonials, metrics) can replace mock placeholders without a rebuild, so that
    Phase 3+ content updates are additive, not structural.

## Implementation Decisions

- **New app:** `apps/landing` — Next.js (App Router), TypeScript, Tailwind, matching
  `apps/demo`'s stack. One responsive codebase; no separate mobile-web build. Deploy
  target (Phase 3): `app-juli.com` (replacing the temporary App Review placeholder
  currently served by `apps/dashboard`).
- **Design authority for tokens/voice only:** reuse `docs/product/design/design.md`
  (color, typography, spacing, motion tokens) and `soul.md` (brand personality, voice) via
  `packages/theme` (Phase 2.6). The landing page's *content sections and IA* are defined
  in this PRD, not in `docs/product/design` — that package's root authorities are scoped
  to the four-destination app (its own README states this explicitly).
- **Sections (initial):** Hero · Why Juli (problem/solution story) · Feature highlights
  (recommendations, approval gate, execution tracking, analytics evidence) · CTA into
  Demo · footer. Content is mock/placeholder copy and static imagery — no real
  screenshots or metrics required for this phase.
- **Component reuse:** consume `packages/ui` (buttons, cards, badges) and
  `packages/theme` extracted during Phase 2.6 rather than re-implementing equivalents.
- **CTA target:** link directly into `apps/demo` in Mock mode (no cross-app state
  passing needed — Mock mode requires no auth).
- **Analytics/telemetry:** defer PostHog wiring to Phase 3 (real deployment); Phase 2.7
  ships UI only.

## Testing Decisions

- Section-level rendering tests (hero, story, features, CTA, footer) confirming required
  copy/CTA elements are present.
- Responsive tests verifying the two required breakpoints (web, mobile-web) preserve
  identical content and CTA behavior.
- A test asserting the primary CTA links to the Demo's Mock mode entry point.
- Visual token usage tests (e.g. lint rule or snapshot) confirming no hardcoded colors
  outside `packages/theme`'s semantic tokens, matching `design.md`'s anti-pattern list.
- Follow existing test layout conventions in `apps/dashboard/src/__tests__/` for
  structure and naming.

## Out of Scope

- Real backend calls, real analytics/lead-capture integration (Phase 3, and only if a
  concrete need — e.g. contact form — is scoped then).
- Public deployment/DNS/HTTPS for `app-juli.com` pointing at `apps/landing` (Phase 3).
- Demo build itself (Phase 2.6 — separate PRD).
- Adding a formal Landing Page spec into `docs/product/design` (kept out of that
  package's scope per ADR-024; this PRD is the landing page's IA source of truth).
- PostHog/behavior analytics instrumentation (Phase 3).

## Further Notes

- **Risk:** visual drift between `apps/landing` and `apps/demo` if `packages/theme` isn't
  consistently used — mitigated by the visual-token usage test above.
- **Rollout:** no production users affected — `apps/landing` is unreachable publicly
  until Phase 3 deploys it and repoints `app-juli.com`.
- **Follow-up:** once real content (screenshots, metrics, testimonials) exists, replace
  mock placeholders in a later slice; no structural rebuild expected given the section
  layout chosen here.
