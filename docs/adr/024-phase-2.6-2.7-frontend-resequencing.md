# ADR 024: Phase 2.6/2.7 frontend resequencing, Demo mock/sign-in toggle, and app boundaries

## Status
Accepted

**Builds on:** [ADR-023](023-four-destination-analytics-ownership.md) (four-destination IA).
**Amends:** [`phase-3-landing-demo.md`](../product/phases/phase-3-landing-demo.md) scope;
[`EXECUTION.md`](../../EXECUTION.md) Phase 3 brief.
**Does not change:** Phase 3.5 scope/brief (explicitly left as-is per grill, 2026-07-15).

## Context

`docs/product/design/` (the open design system) is now the canonical IA for the
four-destination app (Home, Decisions, Analytics, Settings — ADR-023), targeting
`apps/dashboard`. Separately, `phase-3-landing-demo.md` still describes a different,
older two-screen Demo IA (Home + Actions, mock-only, no login) for a not-yet-scaffolded
`apps/demo`. `EXECUTION.md` Phase 3 bundled Landing Page + Demo frontend build, mock data,
and public deployment into one phase.

The product now wants the Demo to run the ADR-023 IA (not the retired two-screen IA), and
wants frontend build-out (mock data) decoupled from backend wiring + public deployment so
each can ship and be reviewed independently. It also wants the Demo to anticipate real
sign-in/OAuth without building it yet.

## Decision

1. **Split Phase 3's frontend-build scope into two new sub-phases that land before
   Phase 3:**
   - **Phase 2.6** — Demo frontend, mock data only, `apps/demo`, one responsive
     Next.js codebase covering web + mobile-web breakpoints.
   - **Phase 2.7** — Landing Page frontend, mock/static content only, `apps/landing`,
     one responsive Next.js codebase covering web + mobile-web breakpoints.
   - **Phase 3** narrows to: wire both apps to a working backend using real data, deploy
     both to their target domains, and prove the end-to-end pipeline for both surfaces.
     Phase 3.5's brief is unchanged by this ADR.

2. **`apps/demo` adopts the ADR-023 four-destination IA** (Home, Decisions, Analytics,
   Settings) — not the retired two-screen Home+Actions IA. `phase-3-landing-demo.md`'s
   two-screen IA section is superseded.

3. **`apps/demo` ships a Mock/Sign-in mode toggle in Phase 2.6.** Mock mode is the
   default, requires no authentication, and is fully interactive over hardcoded/mock
   data. The Sign-in mode entry point exists in the UI but is **disabled** (non-functional
   stub) in Phase 2.6 — no real OAuth, no real backend calls. Phase 3 implements and
   enables Sign-in mode: real TikTok OAuth connect plus real backend data for one
   pre-connected reference shop. Mock mode remains available after Phase 3 ships.

4. **`apps/landing` is a separate product from `apps/demo`/`apps/dashboard`,** with its
   own IA defined in its Phase 2.7 PRD — not part of `docs/product/design`'s scope (that
   package's root authorities are scoped to the four-destination app per its own README).
   `apps/landing` reuses `docs/product/design`'s visual tokens and brand voice
   (`design.md`, `soul.md`, `colors_and_type.css`) for consistency only.

5. **Shared UI/theme extraction starts in Phase 2.6**, not Phase 3.5 as
   `migration-plan.md` previously planned. `packages/ui` and `packages/theme` are
   scaffolded and populated as `apps/demo` is built, so `apps/landing` (2.7) and the
   eventual `apps/dashboard` ADR-023 rebuild (Phase 3.5) reuse the same components
   instead of re-deriving them.

6. **`apps/dashboard` is untouched by this ADR.** It keeps serving the legacy App Review
   placeholder at `app-juli.com` until Phase 3 replaces that surface with `apps/landing`.
   Its own ADR-023 rebuild with real auth remains Phase 3.5 scope.

## Rationale

Decoupling frontend build (mock data, reviewable independently) from backend wiring and
public deployment lets each ship as a small, demoable slice instead of one large Phase 3
delivery. Building the Sign-in toggle now — disabled — means Phase 3 only has to
*implement* the OAuth/real-data path behind an existing UI seam, not design new IA under
deployment pressure. Giving `apps/demo` the ADR-023 IA now (instead of a one-off two-screen
IA) means the Demo previews the real product shape sellers will eventually use, and the
component investment is not thrown away.

## Consequences

- `phase-3-landing-demo.md` must be rewritten: drop the two-screen Home+Actions IA and the
  "no real TikTok connection" boundary (Phase 3 now adds OAuth for the Demo's Sign-in
  mode); redefine Phase 3 success criteria as real-data deployment for both LP and Demo.
- `EXECUTION.md` Phase overview/architecture tables need new Phase 2.6/2.7 rows between
  2.5 and 3; the Phase 3 brief needs to match the new scope. Phase 3.5's brief is
  deliberately left unchanged — likely scope overlap with Phase 3.5 (multi-tenant
  onboarding) will be reconciled in a future grill once Phase 3 ships.
- `migration-plan.md`'s PR sequence (`3-a` scaffold apps/landing+demo, `3.5-a` extract
  packages/ui) is stale against this ADR and needs a follow-up pass to renumber against
  2.6/2.7/3.
- `phase-2.5-deployment.md`'s domain strategy table description of `demo.app-juli.com`
  ("Interactive Demo (mock storytelling)") needs a follow-up note about the mock/sign-in
  toggle.
