# ADR-050: CDP slice 3.5-C — two gated exits (C1 warm Sign-in, C2 cold-start)

**Status:** Accepted  
**Date:** 2026-07-30  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-048](048-cdp-webhook-first-spine-dual-credential.md), [ADR-038](038-phase-2.10-dual-layer-pipeline.md),
[ADR-034](034-tiktok-business-oauth-redirect-urls.md), [ADR-029](029-phase-2.9-analytics-historical-backfill.md).  
**Does not change:** CDP slice 3.5-A/B (Phase 2.10 Analytics/Decisions spine); Demo UI Fix Track B scope;
EXECUTION Phase 3.5 Full Web Application brief (`apps/dashboard` rebuild); 3.5-D real execution workers (separate PRD).

## Context

CDP slice **3.5-C** must design four gaps not yet implemented: OAuth → **`seller_connect`**
credential acquisition, **cold-start backfill** for zero-history shops, **authenticated
multi-tenant read-path** (session-bound `shop_id`, never client-suppliable), and a shared
Partner rate limiter keyed per credential+endpoint.

Bundling all four into one release couples the highest-risk security surface (session
tenancy + read APIs) with the most complex ingest work (progressive 30–90d backfill,
checkpoint pagination, fleet rate limits). EXECUTION already ladders **Phase 3**
(reference-shop Sign-in) before **Phase 3.5** (self-serve multi-tenant).

Demo UI Fix may stub Login cold-start UX via fixtures in parallel; real OAuth should not
wait for the cold-start engine.

## Decision

**3.5-C is one PRD with two gated exits:**

| Exit | Delivers | Explicitly deferred |
|------|----------|---------------------|
| **C1 — Warm Sign-in** | Real TikTok Shop OAuth → `seller_connect` rows; token refresh; **authenticated read APIs** resolving `shop_id` from session; Login mode on Demo for **one pre-connected reference shop** (warm path — Fujiwa-equivalent history already in Postgres) | Cold-start backfill engine; self-serve connect for arbitrary new shops |
| **C2 — Cold-start fleet** | **Cold-start backfill engine** (30–90d progressive per KPI domain, older async, resumable checkpoints per shop+domain+window); self-serve new shops; shared Partner rate limiter per credential+endpoint | — |

Additional locks:

- **Demo UI Fix Login stub** may preview C2 cold-start UX (fake OAuth + fixture **shop
  readiness** envelopes) while C1 ships real OAuth on the warm reference shop.
- **CDP slice 3.5-D** (real execution workers) waits on **C1 credentials at minimum**;
  C2 is not required before first approve-gated Partner writes on the reference shop.
- **Phase 2.9 `analytics_backfill`** remains Fujiwa historical warm — not the cold-start
  engine (see CONTEXT **Cold-start backfill**).

## Consequences

- 3.5-C PRD sections and exit gates must label C1 vs C2; issues slice on C1 before C2
  unless path-disjoint (e.g. contract stubs in Demo UI Fix).
- Security review gates **C1** authenticated read path before **C2** opens self-serve
  tenancy at scale.
- C1 Login mode can show full Analytics KPI envelopes immediately for the reference shop;
  cold-start progress UI is fixture-driven until C2.
- Rate limiter key migration (shop-scoped → credential-scoped) lands in C2 when fleet
  cold-start and multi-credential contention matter.

## Options considered

| Option | Outcome |
|--------|---------|
| One combined 3.5-C release (OAuth + cold-start + self-serve together) | Rejected — delays Sign-in value; couples security review with backfill engine |
| Two separate PRDs (C1 doc + C2 doc) | Rejected — splits one bounded context; harder to trace credential → backfill → read-path dependencies |
| C2 before C1 (cold-start engine first) | Rejected — no real `seller_connect` or session read path to exercise |
| **One PRD, two gated exits (chosen)** | Aligns EXECUTION Phase 3 → 3.5 ladder; de-risks tenancy before fleet scale |
