# ADR 029: Phase 2.9 analytics historical backfill (shared schema, call budget)

## Status
Accepted

## Context

Phase 2.9 needs historical TikTok Shop Analytics for Fujiwa (2026-03-16 →
`latest_available_date`) so Demo/Dashboard Analytics and a later pricing-model
dataset can share one Supabase shape. Alternatives: a parallel research mart;
full Analytics endpoint fan-out (per-product / per-live minute); including Ads
despite unverified Marketing contracts; treating Partner GMV as Net Revenue;
running the ~4-month pull as one same-day quota mega-batch.

Observed Partner call logs: ~46% success near 1000 calls/run, ~78% near 400 —
so unbounded backfill bursts are unreliable. Exact Partner numeric quotas are
unpublished; Juli calibrates from `100005` and a local ~10 req/min/endpoint bucket.

## Decision

- We will: Reuse `analytics_performance_intervals` (and related analytics tables)
  as the **single** schema for Phase 2.6 shape, 2.9 history, and Phase 3 real
  data — no parallel mart.
- We will: Allow **additive nullable columns** on that table for metrics not yet
  modeled (`live_hours`, `live_sessions`, `active_products`, `new_products`, and
  similar) via schema-only Alembic migrations.
- We will: Backfill endpoint set **A-2, A-36, A-34, A-28, A-29, A-37** (Revenue
  core + Product funnel without Impressions/Views + LIVE + shop Customers).
  Active/New from **A-2 Search Products** (not A-3). Persist **GMV (TikTok)** in
  `gmv` — never alias as Net Revenue. **Ads out of 2.9.** Skip A-26/A-27 and
  A-33/A-31/A-32 fan-out for exit.
- We will: Soft-cap ~350–400 Partner calls per run (hard stop before ~500). The
  ~4-month backfill is an **idempotent, resumable job over hours or multiple
  days** — partition by `(shop_id, bucket, date)` (or equivalent), **upsert**
  completed partitions, **never re-download** them on resume; each run exits
  cleanly so the next continues. Prefer multi-day `intervals[]` where the API
  returns daily buckets (A-36/A-29); use 1-day windows for A-34 (window-total
  payload) and A-37 (per-day path).
- We will: Run 2.9 **parallel** to 2.6/2.7 (non-blocking). Exit coverage ≥95%
  days for A-36+A-29, ≥90% for A-34; gaps logged and resumable.
- We will not: Wire Demo/Dashboard UI or a pricing-model fit/export contract in
  2.9; require every credentialed shop for exit (Fujiwa only; `shop_id`-parameterized);
  design backfill as a single quota-day mega-batch.

## Consequences

- Phase 3 can read warm history without a schema migration fork.
- Backfill is expected to span multiple budgeted runs across a day or several
  days; wall-clock “finish today” is not an exit criterion.
- Product Impressions/Views remain unavailable until a later A-33 (or better)
  slice; PRD must list them as out of 2.9 must-have.
- Active/New may fall back to point-in-time counts if A-2 cannot time-travel.
- Pricing-model export/fit remains a follow-on once the owner specifies it.
