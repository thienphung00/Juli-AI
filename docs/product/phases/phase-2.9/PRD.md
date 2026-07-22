# PRD: Phase 2.9 — Analytics Historical Backfill (Shared Schema)

> **Canonical docs:** [`EXECUTION.md`](../../../../EXECUTION.md) Phase 2.9 brief ·
> [ADR-029](../../../adr/029-phase-2.9-analytics-historical-backfill.md) (shared schema,
> call budget, resumable partitions, GMV mapping) ·
> [`contract-collection.md`](../../../integrations/tiktok_api/contract-collection.md)
> (A-2, A-28, A-29, A-34, A-36, A-37) ·
> [`rate-limits.md`](../../../integrations/tiktok_api/rate-limits.md) ·
> [`CONTEXT.md`](../../../../CONTEXT.md) (Phase 2.9 + GMV glossary).
>
> **Parent issue:** [#462](https://github.com/thienphung00/Juli-AI/issues/462) — filed via
> `to-prd` from grill-with-docs (2026-07-22).
>
> **Child slices (`to-issues`):** [#463](https://github.com/thienphung00/Juli-AI/issues/463)
> schema · [#464](https://github.com/thienphung00/Juli-AI/issues/464) partitions ·
> [#465](https://github.com/thienphung00/Juli-AI/issues/465) budget ·
> [#466](https://github.com/thienphung00/Juli-AI/issues/466) revenue ·
> [#467](https://github.com/thienphung00/Juli-AI/issues/467) product ·
> [#468](https://github.com/thienphung00/Juli-AI/issues/468) LIVE ·
> [#469](https://github.com/thienphung00/Juli-AI/issues/469) catalog ·
> [#470](https://github.com/thienphung00/Juli-AI/issues/470) orchestrator ·
> [#471](https://github.com/thienphung00/Juli-AI/issues/471) coverage ·
> [#472](https://github.com/thienphung00/Juli-AI/issues/472) HITL Fujiwa run.

## Problem Statement

Juli needs historical shop performance in Supabase so Demo/Dashboard Analytics and a
later pricing model can share one schema. Today’s analytics poll covers short windows;
we do not yet have a reliable ~4-month history (from 2026-03-16) for Revenue, Product
funnel, and LIVE on the Fujiwa reference shop. A naïve “pull everything in one day”
approach fights Partner API reliability (~78% success near 400 calls; ~46% near 1000).

## Solution

Run **Phase 2.9** as a **parallel, non-blocking** track beside Phase 2.6/2.7: an
**idempotent, resumable** historical backfill into the existing analytics schema
(sparse columns OK; additive nullable columns where needed). Use only verified Partner
endpoints **A-2, A-36, A-34, A-28, A-29, A-37**. Soft-cap ~350–400 calls per run; continue
over hours or multiple days without re-downloading completed partitions. Persist
**GMV (TikTok)** — not Net Revenue. No Demo/Dashboard UI wiring and no pricing-model
fit in this phase (owner specifies pricing dataset steps later).

## User Stories

1. As a data engineer, I want a shop-parameterized backfill job for Fujiwa first, so that
   Phase 3 can reuse the same path for other connected shops without a schema fork.
2. As a data engineer, I want the backfill window to start at 2026-03-16 and end at TikTok’s
   `latest_available_date`, so that history matches what Partner Analytics can actually serve.
3. As a data engineer, I want each run soft-capped near 350–400 Partner calls (hard stop
   before ~500), so that success rates stay near the observed ~78% regime.
4. As a data engineer, I want the job to exit cleanly when the call budget is exhausted, so
   that the next run continues later the same day or on another day.
5. As a data engineer, I want progress tracked per `(shop, bucket, date)` partition, so that
   completed days are never re-downloaded on resume.
6. As a data engineer, I want upserts into the shared analytics intervals table, so that
   re-runs are idempotent and safe.
7. As a backend developer, I want Revenue-core daily GMV, orders, customers, and derived AOV
   stored for ≥95% of calendar days in the window, so that revenue forecasting has a usable
   series.
8. As a backend developer, I want monthly GMV defined as the sum of daily GMV, so that we
   do not invent a separate Partner “monthly revenue” call.
9. As a backend developer, I want shop Customers filled via A-37 (per-day), so that the
   Revenue bucket is complete without guessing from product lists.
10. As a backend developer, I want Product funnel CTR, conversion (click-order rate), and
    product orders from A-34 for ≥90% of days, so that product-level optimization impact
    can be studied later.
11. As a backend developer, I want Active and New product counts from A-2 Search Products
    (status + create_time), with a documented fallback to point-in-time totals if
    catalog-by-day is impossible, so that catalog metrics are honest.
12. As a backend developer, I want LIVE hours, session counts, views, impressions, orders,
    GMV, and conversion from A-28 + A-29 only, so that we avoid per-live minute/product
    fan-out.
13. As a product owner, I want Ads spend/impressions/clicks/orders explicitly out of Phase
    2.9, so that unverified Marketing APIs cannot block the phase.
14. As a product owner, I want Product Impressions and Product Views out of must-have
    (A-34 does not expose them in the verified contract), so that we do not force A-33
    fan-out.
15. As a platform owner, I want Phase 2.9 not to block Phase 2.6 or 2.7 exit gates, so that
    Demo and Landing can ship independently.
16. As a frontend engineer (Phase 3), I want the same Supabase analytics schema that mock
    Analytics shapes against, so that Sign-in real data does not require a parallel mart.
17. As a reviewer, I want a coverage report (days present per bucket, gaps, cursor state),
    so that exit (≥95% A-36+A-29, ≥90% A-34) is measurable.
18. As an operator, I want `100005` / rate-limit and transient failures to retry with
    backoff without advancing the failed partition, so that flaky Partner responses do
    not corrupt progress.
19. As a security-conscious engineer, I want Fujiwa production reads only (no Section B
    writes), so that backfill cannot mutate shop state.
20. As an ML/pricing stakeholder, I want historical rows in Supabase first, with pricing
    export/model instructions deferred, so that model work can start once data exists
    without blocking this phase’s exit.
21. As a schema owner, I want additive nullable columns for live hours, live sessions,
    active products, and new products when missing, so that new metrics stay on one table.
22. As a maintainer, I want GMV clearly labeled and never called Net Revenue in docs or
    column semantics, so that Main KPI Net Revenue is not confused with Partner GMV.

## Implementation Decisions

### Modules (by responsibility)

1. **Analytics historical backfill runner** — orchestrates budgeted runs; selects next
   incomplete partitions; stops at soft call cap; records coverage.
2. **Partition progress store** — durable cursor / completion flags per
   `(shop_id, bucket, date)` (or equivalent); skip completed partitions on resume.
3. **Partner analytics fetch adapters** — A-2, A-36, A-34, A-28, A-29, A-37 with existing
   signing, rate limiter, and error taxonomy (`100005` → backoff).
4. **ETL normalizers → shared intervals** — map Partner payloads into
   `analytics_performance_intervals` (and related rows); sparse columns OK; upsert by
   snapshot key.
5. **Schema migration (DDL-only)** — additive nullable columns for live hours, live
   sessions, active products, new products as needed ([ADR-029](../../../adr/029-phase-2.9-analytics-historical-backfill.md));
   `live_hours`, `live_sessions`, `active_products`, and `new_products` on
   `analytics_performance_intervals` are the shared Phase 2.6 / 2.9 / 3 contract.
6. **Coverage reporter** — computes day coverage vs exit thresholds for the PRD gate.

### Endpoint → bucket map

| Bucket | Endpoints | Notes |
|--------|-----------|--------|
| Revenue core | A-36, A-37 | GMV/orders from A-36; customers from A-37; AOV derived; monthly = sum of daily GMV |
| Product funnel | A-34, A-2 | Daily A-34 windows (payload is window-total); Active/New via A-2 |
| LIVE | A-28, A-29 | Hours/sessions/views/impressions from A-28; daily overview from A-29 |

Prefer multi-day ranges only where the API returns daily `intervals[]` (A-36, A-29).
Use **1-day** windows for A-34 and A-37.

### Scale assumptions (Fujiwa)

- ~129 calendar days in window; ~117 products; A-34 ~3 pages/day at page_size 50.
- ~550–600 successful calls total ≈ ~2 budgeted runs at ~400 attempts — **not** one
  mega-batch; expect continuation across hours or days.

### Architectural decisions

- Shared schema only ([ADR-029](../../../adr/029-phase-2.9-analytics-historical-backfill.md)).
- Parallel to 2.6/2.7; non-blocking.
- Fujiwa exit; `shop_id`-parameterized for Phase 3.
- No Demo/Dashboard UI; no new seller-facing read API required for exit.
- Pricing-model dataset/export/fit **deferred**.

### Assumptions

- Partner will continue to serve analytics history back to 2026-03-16 for Fujiwa.
- Existing OAuth/credential path for Fujiwa remains valid for Section A reads.
- Local RateLimiter (~10 req/min/endpoint) and Partner `100005` both apply; soft cap
  is the primary governor for run size.

## Testing Decisions

- Prefer tests of **external behavior**: partition not re-fetched when complete; upsert
  idempotency; call-budget stop; coverage math; mapper field contracts from sanitized
  fixtures.
- Test modules: backfill runner, partition progress, ETL expanders for A-36/A-34/A-28/
  A-29/A-37/A-2, coverage reporter.
- Prior art: analytics poll ETL upsert tests and Fujiwa polling orchestration tests —
  extend patterns rather than inventing a second harness.
- Do not require live Partner calls in CI; use contract fixtures / recorded responses.

## Out of Scope

- Demo/Dashboard UI wiring and Phase 3 Sign-in UX.
- Pricing-model training, export format, or impact quantification notebooks (follow-on).
- Ads / Marketing API metrics.
- Product Impressions / Product Views (needs A-33 or better — deferred).
- A-26 minute LIVE, A-27 per-live products, A-31/A-32 SKU detail fan-out.
- Multi-shop exit (parameterize only; Fujiwa is the exit shop).
- Net Revenue computation (returns/fees); store GMV only.
- Blocking Phase 2.6 / 2.7 exit gates.

## Further Notes

- **Risks:** Partner date-range limits unknown — may need smaller chunks; A-2 may not
  support true historical Active/New (fallback to point-in-time); success-rate variance
  may require more than two runs.
- **Observability:** log attempts, successes, `100005`, partition advances, coverage %.
- **Rollout:** operator-triggered or manually scheduled budgeted runs until coverage
  gate met; no requirement to finish in one quota day.
- **Follow-ups:** pricing dataset instructions from owner; optional A-33 slice for
  impressions/views; Phase 3 UI on warm history; EXECUTION Phase 2.9 row links this PRD.

## Exit Gate

- [ ] Additive schema columns (if needed) applied via schema-only migration
- [ ] Resumable backfill job with partition progress + ~400-call soft cap
- [ ] Fujiwa window 2026-03-16 → `latest_available_date` loaded for endpoint set A
- [ ] ≥95% days with Revenue (A-36) + LIVE overview (A-29); ≥90% days with A-34
- [ ] Coverage report published; gaps listed and resumable
- [ ] GMV labeled correctly; Ads and Product Impressions/Views documented as out
- [ ] No requirement that Demo/Landing UI consume the data in this phase
