# ADR-037: Phase 2.10 — Demo real-data KPI wire without auth

**Status:** Accepted — **phase shape superseded in part** by [ADR-038](038-phase-2.10-dual-layer-pipeline.md)  
**Date:** 2026-07-27  
**Superseded by (in part):** [ADR-038](038-phase-2.10-dual-layer-pipeline.md) — the 2.10-A /
2.10-B phase shape and the Redis stance for product reads. The **no-auth boundary** (public,
unauthenticated Demo; no visitor OAuth) is **retained** and remains this ADR's live decision.  
**Deciders:** grill-with-docs (Architect)

**Amends:** [ADR-024](024-phase-2.6-2.7-frontend-resequencing.md) Phase 3 timing for
Sign-in / OAuth; [`EXECUTION.md`](../../EXECUTION.md) Phase 3 brief (insert 2.10
before full Phase 3).  
**Does not change:** Phase 3.5 multi-tenant / self-serve connect; ADR-029 shared
analytics schema; ADR-021 Action Card manual-refresh semantics.

## Context

Phase 2.6 shipped `apps/demo` on mock data; Phase 2.9 warmed shared Supabase
analytics history for the reference shop (Fujiwa). ADR-024 / Phase 3 still bundle
(1) Landing deploy to `app-juli.com`, (2) enabling Demo Sign-in with TikTok OAuth,
and (3) wiring real backend data. Landing frontend (2.7) is not shipped yet, and
product wants the Demo’s Analytics visual layer on **real masked KPIs** this week
**without login**.

Alternatives: keep waiting for full Phase 3 (blocks on LP + OAuth); rename Phase 3
exit to drop Sign-in (blurs the ADR-024 public-auth story); ship full Phase 3 as
written (conflicts with “no login”).

## Decision

1. Insert **Phase 2.10 — Demo real-data KPI wire** between 2.9 and Phase 3.
2. Phase 2.10 keeps Demo **public and unauthenticated**. No TikTok OAuth, no
   visitor accounts. Sign-in UI stays a disabled stub (same as 2.6).
3. Demo serves **masked reference-shop** metrics (Fujiwa / `production_read`) via
   backend read APIs. **Phase shape superseded by [ADR-038](038-phase-2.10-dual-layer-pipeline.md):**
   **2.10-A** Analytics wire, then **2.10-B** Decision Layer wire — both on real
   precomputed data; Home teasers / Settings may stay mock until explicitly scoped.
4. Redis stance for product reads superseded by ADR-038 (**required** read-through
   cache). Auth boundary unchanged: no visitor OAuth in 2.10.
5. **Deferred to remaining Phase 3:** Landing `app-juli.com` cutover, enabling
   Sign-in/OAuth, PostHog engagement exit as written in the Phase 3 brief.

## Consequences

- `EXECUTION.md` and `phase-3-landing-demo.md` need a 2.10 brief and a narrowed
  Phase 3 that no longer treats “first real Demo data” as the same gate as OAuth.
- MODULES Frontend / Data Pipeline / Cross-cutting planned features should track
  2.10 KPI T/L + Demo wire + Redis cache.
- Public Demo will show real commercial patterns; masking rules must be explicit
  in the 2.10 PRD (shop name, IDs, SKU labels) so Fujiwa is not trivially
  identifiable.

## Options considered

| Option | Outcome |
|--------|---------|
| A — Interim Phase 2.10 (chosen) | Ship real masked KPIs without auth; defer LP + OAuth |
| B — Phase 3 data-only (amend ADR-024 exit) | Same technical work; weaker phase naming clarity |
| C — Full Phase 3 as ADR-024 | Requires login/OAuth + Landing — rejected for this week |
