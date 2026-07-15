# Phase 3 — Landing Page + Demo, Real Data

> **Tier 1 — real-data + deployment scope.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** wiring real backend data into the Demo, enabling Sign-in mode, and deploying
> both public surfaces.  
> **Does not own:** frontend build-out for either surface (mock data) —
> [`phase-2.6/PRD.md`](phase-2.6/PRD.md) (Demo) and [`phase-2.7/PRD.md`](phase-2.7/PRD.md)
> (Landing); backend pipeline mechanics (`phase-2-mvp.md`); production dashboard
> multi-tenant auth (`phase-3.5`, unchanged by this revision).

**Goal:** Deploy the Landing Page and Demo publicly with a working backend on real data,
and prove the end-to-end pipeline for both surfaces.

**Revision note (2026-07-15, [ADR-024](../../adr/024-phase-2.6-2.7-frontend-resequencing.md)):**
This phase previously bundled frontend build (mock data) with backend wiring and
deployment, and described a two-screen Home+Actions Demo IA. That IA is **retired** —
`apps/demo` now implements the [ADR-023](../../adr/023-four-destination-analytics-ownership.md)
four-destination IA (Home, Decisions, Analytics, Settings), built with mock data in
[Phase 2.6](phase-2.6/PRD.md). The Landing Page's frontend is built with mock/static
content in [Phase 2.7](phase-2.7/PRD.md). Phase 3 now covers only what those two phases
deliberately deferred: real backend data, Sign-in mode, and public deployment.

---

## Success criteria

Phase 3 exits when:

1. **`apps/landing` is deployed** to `app-juli.com`, replacing the temporary App Review
   placeholder currently served by `apps/dashboard`.
2. **`apps/demo` is deployed** to `demo.app-juli.com`.
3. **`apps/demo`'s Sign-in mode is enabled** (per [ADR-024](../../adr/024-phase-2.6-2.7-frontend-resequencing.md)) —
   real TikTok OAuth connect plus real backend data, for one pre-connected **reference
   shop** (already authenticated via Phase 2's pipeline validation, e.g.
   Fujiwa/SANDBOX_VN). Mock mode remains available alongside it.
4. **The end-to-end pipeline works live for both surfaces:** for the Demo, poll/ETL →
   feature aggregates → rules-based signals → recommendations → copy → Action Cards
   renders correctly in the ADR-023 IA (Decisions, Analytics) using real data; for the
   Landing Page, the CTA flow into the Demo works end-to-end.
5. **Behavior analytics (PostHog)** collects engagement and messaging metrics on both
   surfaces.

## Products

| App | Domain | Purpose |
|-----|--------|---------|
| **`apps/landing`** | `app-juli.com` | Marketing website — why Juli exists (built Phase 2.7; deployed here) |
| **`apps/demo`** | `demo.app-juli.com` | Interactive product experience — real recommendations, real approval, real execution tracking on one reference shop's data (built Phase 2.6; wired to real data + deployed here) |

---

## What changes from Phase 2.6/2.7

| Concern | Phase 2.6/2.7 | Phase 3 |
|---------|---------------|---------|
| Data source | Mock/hardcoded | Real backend (Phase 2 pipeline output) for one reference shop |
| Demo Sign-in mode | Disabled stub | Enabled — real TikTok OAuth connect for the reference shop |
| Deployment | None (local/preview only) | Public HTTPS on `app-juli.com` / `demo.app-juli.com` |
| Analytics | None | PostHog behavior analytics on both surfaces |

**Per-visitor/self-serve TikTok connection and multi-tenant account management are not in
Phase 3** — Sign-in mode authenticates against the one reference shop only. Opening
self-serve TikTok OAuth to arbitrary public visitors remains Phase 3.5 scope.

---

## Demo information architecture (ADR-023, superseding the retired two-screen IA)

`apps/demo` implements the same four destinations as the canonical
[`docs/product/design`](../design/README.md) IA:

| Destination | Owns |
|-------------|------|
| **Home** | Sparse launcher — exactly two cards: Decisions, Analytics |
| **Decisions** | Recommendations (Approve / Reject / Expand) and In Progress execution tracking |
| **Analytics** | All KPIs, comparisons, forecasts, and reports (including the six Main KPIs) |
| **Settings** | Workflow templates and thresholds |

Design detail lives in `docs/product/design/Screens/` and `Flows/` — Phase 3 does not
redefine IA; it only swaps the data source and enables Sign-in mode inside the app built
in Phase 2.6.

---

## Boundaries

| In scope | Out of scope |
|----------|--------------|
| Real backend data for one reference shop | Per-visitor / self-serve TikTok connection |
| Reference-shop TikTok OAuth (Sign-in mode) | Multi-tenant account/session management |
| Public HTTPS deployment (both domains) | New frontend IA/screens (done in 2.6/2.7) |
| PostHog behavior analytics | `apps/dashboard` ADR-023 rebuild (Phase 3.5) |
| Mock mode remains available | Login/signup for arbitrary visitors |

---

## Relationship to `apps/dashboard`

`apps/dashboard` is a separate app from `apps/demo` and is **not** touched by this phase.
It keeps serving the legacy ADR-014 App Review placeholder at `app-juli.com` until this
phase repoints that domain to `apps/landing`. Its own rebuild to the ADR-023 IA with real,
multi-tenant, per-seller authentication remains [Phase 3.5](../../../EXECUTION.md) scope
(unchanged by this revision).

---

## Exit gate → Phase 3.5

- [ ] `apps/landing` deployed and publicly reachable at `app-juli.com`
- [ ] `apps/demo` deployed and publicly reachable at `demo.app-juli.com`
- [ ] `apps/demo` Sign-in mode live with real reference-shop data end-to-end
- [ ] End-to-end pipeline proven live for the Demo; Landing → Demo CTA flow verified
- [ ] Engagement and messaging metrics collected via PostHog on both surfaces
