# backend/src/juli_backend/services/analytics_backfill

## Purpose

Phase 2.9 analytics historical backfill helpers. Owns the per-run Partner HTTP
call-budget governor (ADR-029) — additive to Redis ``RateLimiter``, not a
replacement. Also hosts bucket partition runners (#466–#469).

## Public API

- ``begin_run(max_attempts=400, hard_limit=499)`` → ``CallBudgetGovernor``
- ``CallBudgetGovernor.record_attempt()`` — count one Partner HTTP try (including retries)
- ``CallBudgetGovernor.record_success()`` / ``record_failure()`` / ``record_rate_limited()``
- ``CallBudgetGovernor.should_stop()`` — soft target reached; orchestrator should pause
- ``CallBudgetGovernor.remaining()`` — attempts left before soft target
- ``CallBudgetGovernor.finish(stopped_reason)`` → structured log dict
- ``CallBudgetGovernor.structured_log_fields()`` — ``attempts``, ``successes``,
  ``failures``, ``rate_limited``, ``stopped_reason`` (`budget` | `complete` | `error`)
- ``BudgetExhaustedError`` — hard limit would be exceeded
- ``backfill_revenue_partition(...)`` → ``skipped`` | ``complete`` | ``failed`` — one-day revenue bucket (#466)
- ``backfill_product_partition(...)`` — one-day A-34 product funnel partition (#467)
- ``run_live_partition(...)`` — LIVE bucket E2E for one calendar day (#468): A-29
  overview + A-28 session list → shop rollup + optional per-session rows; skips
  completed partitions; respects call budget; marks complete only after upserts
- ``run_catalog_partition(...)`` — Active/New via A-2 Search Products (#469)
- ``backfill_analytics_history(...)`` — multi-bucket orchestrator loop (#470): walks
  revenue → live → product → catalog by ascending date; skips completed partitions;
  pauses on ``should_stop()`` with ``stopped_reason=budget`` (exit code 0)
- ``validate_buckets(...)`` — rejects Ads / A-26 / A-27 / A-33 buckets

## Operator command (#470)

Validate CLI flags (partition wiring is programmatic today):

```bash
cd backend
PYTHONPATH=src python -m juli_backend.services.analytics_backfill.cli \
  --shop-id "<shop-uuid>" \
  --start 2026-03-16 \
  --end 2026-07-21 \
  --buckets revenue,live,product,catalog
```

Programmatic entry (worker-style): ``backfill_analytics_history(session, shop_id=...,
start_date=..., end_date=..., run_partition=...)`` with injected partition runners
composing ``backfill_revenue_partition``, ``run_live_partition``,
``backfill_product_partition``, and ``run_catalog_partition``. Multi-day A-36/A-29
batching is deferred — orchestrator calls existing one-day primitives per calendar
day and marks each day complete individually.

## Caller contract

- **Budget exhaust ≠ partition complete.** When ``finish("budget")`` or
  ``should_stop()`` triggers a clean pause, the orchestrator must **not** call
  partition ``mark_complete`` for the in-flight partition. Resume on the next run.
- **Each HTTP attempt counts.** Initial calls and retries each invoke
  ``record_attempt()`` once before sending the request.
- **Coexistence with RateLimiter.** Check Redis rate limits first; this governor
  only caps total attempts per backfill run.

## Dependencies

Budget governor is pure in-memory. Partition runners depend on TikTok resources,
ETL transform, and repos.

## Product partition (#467)

- ``backfill_product_partition(session, shop_id, partition_date, resource, budget, ...)``
  — one calendar-day A-34 paginated fetch; upserts ``grain=product`` rows; marks
  ``product`` bucket complete only when every page succeeds.
- Product Impressions/Views deferred (no A-33 fan-out).

## Catalog partition (#469)

- ``run_catalog_partition(session, shop_id, partition_date, products, ...)`` — A-2
  ``search_all`` → ``active_products`` / ``new_products`` on shop-grain interval row
- ``CatalogCountStrategy.DAILY`` — trailing-7-day New; Active from current status allowlist
  (``ACTIVATE`` minimum)
- ``CatalogCountStrategy.POINT_IN_TIME`` — fallback: Active now + New since
  ``2026-03-16``; grain ``catalog_point_in_time``
- Respects ``AnalyticsBackfillPartitionsRepo`` for bucket ``catalog`` (skip complete,
  ``mark_complete`` on success)

## Out of scope

- Orchestrator loop (#470), coverage reporter (#471)
- Live Partner HTTP client wiring in unit tests
