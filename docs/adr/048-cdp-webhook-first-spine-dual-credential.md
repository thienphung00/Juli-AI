# ADR-048: Webhook-first CDP continuous spine and Demo dual credential model

**Status:** Accepted  
**Date:** 2026-07-30  
**Deciders:** grill-with-docs (Architect)

**Builds on:** [ADR-013](013-operations-pipeline-spine.md), [ADR-021](021-manual-refresh-pipeline-and-action-card-persistence.md),
[ADR-029](029-phase-2.9-analytics-historical-backfill.md), [ADR-031](031-integrations-executor-domain.md),
[ADR-037](037-phase-2.10-demo-real-data-no-auth.md), [ADR-038](038-phase-2.10-dual-layer-pipeline.md),
[ADR-034](034-tiktok-business-oauth-redirect-urls.md).  
**Amends:** ADR-038 reconcile cadence at multi-shop scale (hourly Mock reference-shop
exception remains for 2.10 exit; **daily staggered per-shop reconcile** is the scale
backstop); ADR-037 credential boundary (Mock reference reads stay on `production_read`;
**`seller_connect`** is reserved for a **future Phase 3 Sign-in** release — not this one).  
**Does not change:** Postgres SoT; Redis read-through (not SoT); material webhook set
(ADR-038 §5a); public Mock Demo dry-run execution; Phase 3.5 full multi-tenant scope.  
**Physical model:** ingest paths and A-7 merge land in the medallion layers locked by
[ADR-046](046-cdp-medallion-physical-model.md) (`bronze` append → `silver` upsert → serving
`gold.kpi_envelopes`). **Lambda layers:** webhook-first + targeted fetch = **Speed layer**;
daily staggered reconcile + partition backfill = **Batch layer** — both write serving gold via
Shared Compute ([ADR-047](047-cdp-lambda-layers-prd-split.md)). PRD sequencing: **A0** foundation →
**A1** Speed (material handoff, five Demo KPIs) → **A2** Batch (fleet reconcile, dual budgets);
**3.5-B** blocked on **A1**, not full A2.  
**Out of scope for this release (Demo UI fix + CDP P0 slices):** OAuth, Sign-up, Sign-in
implementation, or enabling the Demo Sign-in control — the stub stays **disabled** and
non-functional; only **Mock mode** + Fujiwa **`production_read`** ship now.

## Context

Phase 2.10 (ADR-038) defined the production-shaped **continuous CDP spine** — material
webhooks → targeted API fetch → raw Postgres → transform/compute → precomputed envelopes
— but production ingress on the **deployed** API mount (`api/routes/webhook_tiktok.py`)
still hands off to ETL via `make_etl_handoff` **without** enqueueing KPI compute after
material events. Demo KPIs therefore advance mainly from poll/backfill, not the
webhook-first path the product locked.

Separately, Fujiwa polling already wires Analytics GET targets (A-25, A-31–A-39 per
#424) but several gaps waste Partner quota or leave KPI holes: A-38/A-39 bestselling
calls that do not persist; unbounded A-31/A-33 detail fan-out at list-page scale;
missing A-7 cancellations poll vs webhook #11 (`REVERSE_STATUS_UPDATE`); finance
unsettled/statement surfaces deferred; video performance list analytics not yet in the
compute path. Full poll on every material webhook would not scale toward ~100 shops.

Credential policy also needed a grill lock before CDP P0 + Demo UI work: **Mock mode**
must keep Fujiwa **`production_read`** for the public masked reference shop (no visitor
OAuth). **Sign-in mode** (OAuth / Sign-up / Sign-in) is a **future Phase 3 release** —
not the same ship train as current Demo UI + CDP P0. This ADR records the **future dual
credential design** so Phase 3 does not cross-mix `production_read` and per-shop
**`seller_connect`** when Sign-in eventually ships; it does **not** authorize Sign-in
implementation in the current release.

## Decision

1. **Wire the deployed webhook material handoff end-to-end (P0 spine gap):** On the
   production mount (`webhook_tiktok.py` → `make_etl_handoff`), after successful ETL
   handoff for **material** catalog types (ADR-038 §5a), enqueue shop-scoped
   **fetch-then-precompute** (Celery). Reuse existing poll/backfill callables with
   **targeted fetch** for the affected domain — not a full Fujiwa poll cycle on every
   event.

2. **P0 ingest/API priorities (sequenced):**
   - **A-7 cancellations poll** — `POST /return_refund/202602/cancellations/search` —
     plus reconcile with webhook #11 (`REVERSE_STATUS_UPDATE`).
   - **A-38/A-39 fix** — persist bestselling product/video rows via ETL **or** stop
     calling (no wasted Partner quota on rank snapshots that never land in Postgres).

3. **P1 ingest/API priorities (sequenced after P0):**
   - **Finance unsettled + statements** — poll path; finance webhooks remain deferred.
   - **Video performance list analytics** — list-tier Partner reads into the shared
     analytics schema where KPI contracts require them.

4. **Webhook-first + targeted fetch + staggered reconcile (scale shape):**
   - **Webhook-first:** material events drive enqueue; polling is gap reconciliation,
     not the primary freshness path (reaffirms ADR-021/038).
   - **Targeted fetch:** post-webhook jobs fetch only the Partner resources implicated
     by the event (orders, returns, product, inventory, relevant analytics windows) —
     not unconditional A-31/A-33 detail fan-out across entire list pages.
   - **Daily staggered per-shop reconcile** as the multi-shop backstop (shop-scoped
     schedule spread across the day). ADR-038's **hourly** Mock reference-shop job
     remains valid for 2.10 exit on the single Fujiwa tenant; staggered daily reconcile
     is the pattern for scale beyond that exception.
   - **Stop unbounded A-31/A-33 fan-out** during routine poll/webhook-driven paths;
     detail fetches require an explicit trigger (backfill partition, targeted gap, or
     future scoped issue) — not automatic expansion from every list page.

5. **Demo dual credential model (future design — not this release):**
   - **This release (Demo UI fix + CDP P0):** **Mock mode only.** Public Demo reads and
     reference-shop ingest continue on Fujiwa **`production_read`**. The Demo Sign-in
     control remains **disabled** (stub non-functional). No OAuth, Sign-up, or Sign-in
     implementation.
   - **Mock / public Demo (2.10+):** continues **`production_read`** on the configured
     reference shop (Fujiwa) for masked Analytics/Decision reads and server-side ingest.
     No visitor OAuth; no `seller_connect` fallback for reference-shop precompute.
   - **Sign-in / Phase 3 (future):** when Sign-in ships, enable TikTok Shop **seller OAuth**
     (`seller_connect` capability) so **new shops** connect by logging in with TikTok
     on the Demo Sign-in path. Each connected shop uses its own OAuth row for reads and
     (post-approval) writes — isolated from Fujiwa `production_read`.
   - **Dual model (future):** reference `production_read` for public Demo data; per-shop
     `seller_connect` for authenticated new shops. Resolver paths must not cross-mix
     capabilities (reaffirms ADR-030 strict `production_read` isolation for backfill/CLI).

6. **Analytics-first continuous wire sequencing (Track A):**
   - **This release / near-term:** shop update → ETL → compute → **KPI envelope → Demo
     Analytics** on the shared spine.
   - **Next CDP slice:** same compute trigger → **rules scoring → Decision/Action Cards**
     (emission budget; Demo dry-run). Rules evolve toward ML later.
   - **Do not block** Analytics spine delivery on the Decisions continuous wire.

## Consequences

- **Analytics-first, Decisions next:** Backend/CDP work sequences Analytics envelope delivery
  before wiring Decisions continuous scoring on the same compute trigger; Demo UI fix
  (Track B) may proceed in parallel but must not assume Decision feed freshness until the
  Track A Decisions slice lands.
- Integrations executor backlog orders: deployed material handoff → P0 A-7 + A-38/A-39 →
  P1 finance + video list → staggered reconcile scheduler — before broad new Analytics UI
  slices that assume fresh cancellation/finance/video fields.
- Issue #532 (material webhook compute enqueue) and deployed wiring are the same spine
  gap; implementation must target the **deployed** route assembly, not only the standalone
  `create_app` test factory.
- Partner call budgets improve when A-38/A-39 stop/no-op and A-31/A-33 lose unbounded
  list fan-out; cancellations + finance polls add bounded P0/P1 cost with explicit reconcile
  rules vs webhook #11.
- **Current release:** no OAuth/Sign-up/Sign-in work; Demo Sign-in control stays disabled;
  Mock + `production_read` only.
- **Future Phase 3 Sign-in:** register Shop OAuth (`/v1/auth/tiktok/callback`), persist
  `seller_connect` rows, and route authenticated Demo reads/compute by `shop_id` — while
  Mock mode keeps reading the server-bound reference shop via `production_read`.
- MODULES Data Pipeline / Integrations / Frontend Cross-cutting should reference this
  sequence when prioritizing CDP vs Demo UI polish.

## Options considered

| Option | Outcome |
|--------|---------|
| Poll-heavy spine (full Fujiwa cycle per webhook) | Rejected — Partner rate limits and compute cost explode at scale |
| Drop A-38/A-39 calls without ETL decision | Rejected — silent quota burn; must persist or stop calling |
| Single credential for Demo (seller_connect only) | Rejected — breaks masked public reference shop without visitor OAuth |
| Keep hourly-only reconcile at 100 shops | Rejected — replaced by daily staggered per-shop backstop at scale |
| New ADR vs heavy ADR-038 amend | **New ADR-048** — locks implementation priority sequence + credential launch policy spanning 037/038/024 |
