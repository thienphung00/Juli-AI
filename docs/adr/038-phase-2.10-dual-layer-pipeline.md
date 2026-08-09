# ADR-038: Phase 2.10 dual-layer pipeline — precompute + required cache

**Status:** Accepted  
**Date:** 2026-07-27  
**Deciders:** grill-with-docs (Architect)

**Refined by (read before treating the pipeline below as current):**
[ADR-041](041-vps-redis-ephemeral-cache-and-celery.md) (Redis operational shape),
[ADR-046](046-cdp-medallion-physical-model.md) (names the bronze/silver/gold/ops schema layers),
[ADR-047](047-cdp-lambda-layers-prd-split.md) (Speed/Batch/Serving freshness split),
[ADR-048](048-cdp-webhook-first-spine-dual-credential.md) (webhook-first spine, dual credential),
[ADR-049](049-demo-analytics-main-kpi-override.md) (Demo Main KPI catalog),
[ADR-050](050-cdp-slice-3-5-c-two-gated-exits.md) (3.5-C gated exits).

**Builds on:** [ADR-013](013-operations-pipeline-spine.md), [ADR-021](021-manual-refresh-pipeline-and-action-card-persistence.md),
[ADR-029](029-phase-2.9-analytics-historical-backfill.md), [ADR-037](037-phase-2.10-demo-real-data-no-auth.md).  
**Amends:** ADR-021’s “Redis optional” stance **for Phase 2.10+ product reads**;
ADR-037 destination scope (Analytics-only) — Decision Layer returns as **2.10-B**.  
**Does not change:** Postgres remains system of record; Redis never SoT; buyer PII
forbidden; no visitor OAuth in 2.10 (ADR-037); Phase 3 Landing + Sign-in still deferred.

## Context

After 2.6 (mock Demo) and 2.9 (analytics backfill), product wants a **production-shaped**
path that scales toward ~100 shops: webhook signals → API fetch → raw Postgres →
transform/aggregate → compute → **precomputed** Analytics + Decision outputs, with
**caching required** because repeated DB assembly of KPI/Decision envelopes is too
expensive for public Demo and future multi-shop reads.

ADR-037 initially scoped 2.10 to Analytics-only with Decisions later. The grill
reframed: wire **both** layers in Phase 2.10 as sequential slices sharing one
pipeline. ADR-021 left Redis optional and compute on manual `POST /v1/action-cards/refresh`
only — insufficient for the event-driven + cache-backed target.

## Decision

1. **Phase 2.10 is two slices sharing one spine:**
   - **2.10-A — Analytics Layer wire:** transform→compute→persist KPI read model;
     Demo Analytics reads precomputed (+ cache); no-auth masked reference shop
     (ADR-037). **Home and Settings stay on Phase 2.6 mock** for 2.10.
   - **2.10-B — Decision Layer wire:** same precomputed KPI/intelligence inputs →
     recommendations / Action Cards on Demo Decisions; **Demo execution is dry-run
     only** (no merchant-credential TikTok writes — Decision §9). Home stays mock.

2. **Canonical pipeline (target for 2.10, designed for multi-shop):**

   ```
   TikTok events → Webhooks + API fetch → Raw Postgres
     → Transform / aggregate → Compute / intelligence
     → Precomputed Postgres + required read-through cache
     → Analytics Layer  |  Decision Layer → (approve) → API execution
   ```

3. **Postgres is SoT for raw + precomputed product rows** (KPI snapshots / envelopes
   and Action Cards). **Redis is required** in 2.10 as read-through cache of those
   envelopes for Demo/API reads — never the only copy of truth; invalidate or
   overwrite on successful compute.

4. **Both product layers consume the same compute outputs** — Decision Layer must
   not maintain a parallel KPI formula path.

5. **Compute triggers by Demo mode (settled — amends earlier hybrid wording):**
   - **Mock mode** (public Demo; Phase 2.10 default — many visitors, one shared
     reference-shop precompute): **curated material webhooks** enqueue
     fetch→compute (not every catalog ACK); plus a **hourly** reconciliation
     recompute for that shop. Visitor **Demo Refresh is fake** — re-reads
     Redis/Postgres envelopes and resets client UI state; it must **not** enqueue
     Transform→Compute. Any public endpoint that could force Analytics/Recommendation
     recompute is **strictly rate-limited** (and should normally be disabled for
     visitors).
   - **Login / Sign-in mode** (Phase 3+; one authenticated user per shop):
     **hybrid** — material webhooks + seller **Demo Refresh** may enqueue real
     recompute (subject to per-shop quotas).
   - Polling remains the gap-reconciliation backstop for raw ingest.
   Amends ADR-021’s refresh-only trigger for 2.10+; keeps reusable pipeline
   callables. Hourly Mock reconciliation is a **narrow scheduler exception** for
   the shared reference shop — not a return to global daily scoring cron.

5a. **Material webhook set for compute enqueue (settled — Option A):** From the
    Phase 2 catalog in [`webhooks.md`](../integrations/tiktok_api/webhooks.md) /
    [`execution_layer.md`](../product/execution_layer.md), **enqueue shop compute**
    only for high-signal shop-performance events:

    | # | Event | Why material |
    |---|-------|--------------|
    | 1 | `ORDER_STATUS_CHANGE` | Orders / Ops / Revenue path |
    | 2 | `REVERSE_STATUS_UPDATE` | Returns / cancellation intake |
    | 5 | `PRODUCT_STATUS_CHANGE` | Listing / product funnel |
    | 12 | `RETURN_STATUS_CHANGE` | Returns KPI path |
    | 27 | `INVENTORY_STATUS_CHANGE` | Inventory availability |
    | 39 | `ACTIVITY_STATUS_CHANGE` | Promotion lifecycle |
    | 67 | `REFUND_SUCCESS` | Refund / revenue quality |
    | 68 | `INVENTORY_CHANGED` | SKU qty — **debounced 15 min per shop** (high volume) |

    **Ingest + workflow-signal only (no compute enqueue):** #3, #4, #11, #21, #24,
    #37, #58, #64, #65 (execution monitors / FBT/path detail). **Account lifecycle
    only:** #6, #7 (pause / re-auth — never KPI compute). Non-subscribed deferred
    types stay ACK-only. Other material types share a light per-shop compute mutex
    to prevent stampede; #68 coalesce window = **15 minutes** (tunable config).

6. **Decision emission ≠ KPI freshness (dual cadence — settled):** Analytics KPIs
   may update when compute runs after material shop events. **Surfaced Decisions**
   use a **Decision emission budget**: daily active-set cap, per-workflow cooldown
   after approve/dismiss/execute, and a soft weekly novelty quota. Starting
   **config defaults** (tunable, not hard product law): max **5** active Decisions
   per shop; **7-day** cooldown per `workflow_key` after terminal action; soft
   weekly cap of **3** newly promoted Decisions into the active set. Candidates
   may still be recomputed; only **surfacing** is throttled.

   **Amendment (2026-08-08, operator decision during Phase 3.5-B / #716).** "Soft"
   was never defined here, and the first implementation read it as a hard gate ahead
   of the active cap — which, since 3 < 5, made `max_active = 5` structurally
   unreachable through fresh candidates and left surfacing slots idle. Settled
   semantics:

   - The **weekly novelty quota is a churn target, not a supply ceiling.** Once it is
     consumed, additional novel candidates may still surface **while the active
     surfaced set is below `max_active`** — they fill remaining slots rather than
     leaving them idle. Candidates within the quota surface first, so the quota still
     shapes *which* Decisions appear.
   - The **per-workflow cooldown stays hard**: a workflow inside its cooldown window
     never surfaces, regardless of free slots.
   - The **active cap stays hard**: it is the only ceiling on the surfaced set.
   - Suppression reason codes must name the gate that actually bound — a candidate
     dropped once the set is full is `active_cap`, not `weekly_novelty_cap`.

   Worked example with defaults and 6 novel candidates in one week: 5 surface, the
   6th is suppressed as `active_cap`, and no slot is left idle.

   **Known consequence — the novelty quota no longer throttles.** Under fill-to-cap,
   novelty never suppresses: when slots are free the overflow fills them, and when
   slots are full the active cap binds instead. `weekly_novelty_cap` is therefore
   **structurally unreachable as a suppression reason**, and the quota degrades to an
   *ordering preference* — within-quota candidates simply get scarce slots first.
   Churn protection now rests entirely on the per-workflow cooldown and the active
   cap. If more than 3 slots free up in a week, more than 3 new Decisions can be
   promoted, which the original "soft weekly cap of 3 newly promoted" wording did not
   anticipate. This is an accepted trade of churn protection for slot utilisation, not
   an oversight. Revisit if Demo feeds prove too volatile.

7. **2.10-A KPI must-haves (settled):** Live shop **GMV (TikTok)** series and
   supporting A-36 traffic fields where present; product funnel (A-34) and LIVE
   (A-28/A-29) charts the warm data supports. Inventory/Ops/CSAT only when
   existing aggregates already compute them — no new Ads/Shop-Status ETL in
   2.10-A. **Never alias GMV as Net Revenue.** Ads (ROAS/CAC/CTR), SPS/AHR/VP,
   and T1 forecast overlays stay truthful `unavailable` (or mock Shop Status)
   unless a later slice adds sources.

8. **Public Demo masking (settled):** **Identity mask, real magnitudes** — alias
   shop display name; redact/hash merchant ids, order ids, and SKU titles to
   stable aliases; keep real GMV/trend magnitudes and chart shapes. Buyer PII
   remains forbidden (not a masking substitute).

9. **Demo Decision execution is dry-run (settled):** On Mock/public Demo (2.10),
   Decision/Action flows that would call TikTok write endpoints must **not** use
   the reference merchant’s credentials and must **not** perform real Partner
   mutations. UX may simulate success/progress against local/demo execution
   records only. Real credentialed execution is Login/Sign-in (Phase 3+) only.

10. **Public Demo read API (settled):** Unauthenticated GETs return masked
    envelopes for the single server-configured reference shop; visitors cannot
    pass arbitrary `shop_id`. Force-recompute stays auth-gated / Mock-disabled.

11. **2.10-B Decision intelligence (settled):** Reuse the Phase 2 rules pipeline
    (`aggregates → rules signals → recommendations → rules copy → Action Cards`).
    Wire it into material/hourly compute. Add tunable **threshold config** and the
    **Decision emission budget** for surfacing. No new ML trainers / classification
    stack in 2.10 — trained T1–T8 remain later phases.

## Consequences

- MODULES Data Pipeline / Intelligence / Frontend / Cross-cutting track 2.10-A then
  2.10-B; EXECUTION gains a 2.10 brief with A/B exit gates.
- ADR-021 remains correct that **pipeline callables** stay reusable; Phase 2.10
  may add **additional triggers** beyond HTTP refresh without rewriting scoring.
- Forecasts / trained T1–T8 in the Analytics box stay phase-gated (display-grade
  rules first unless a later grill promotes trained inference into 2.10).
- ~100-shop scale is a **design constraint** (shop-scoped jobs, idempotent upserts,
  cache keys per shop) — not a requirement to load-test 100 tenants in 2.10 exit.

## Options considered

| Option | Outcome |
|--------|---------|
| Analytics-only 2.10, Decisions later | Rejected after rethink — shared store without Decision wire delays the product loop |
| Redis-primary KPI/Decision store | Rejected — contradicts SoT discipline; recovery/audit painful |
| Defer cache until latency hurts | Rejected for 2.10 — product requires cache as part of the production shape |
