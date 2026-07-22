# backend/src/juli_backend/services/analytics_backfill

## Purpose

Phase 2.9 analytics historical backfill helpers. Owns the per-run Partner HTTP
call-budget governor (ADR-029) — additive to Redis ``RateLimiter``, not a
replacement.

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
- ``run_live_partition(...)`` — LIVE bucket E2E for one calendar day (#468): A-29
  overview + A-28 session list → shop rollup + optional per-session rows; skips
  completed partitions; respects call budget; marks complete only after upserts

## Caller contract

- **Budget exhaust ≠ partition complete.** When ``finish("budget")`` or
  ``should_stop()`` triggers a clean pause, the orchestrator must **not** call
  partition ``mark_complete`` for the in-flight partition. Resume on the next run.
- **Each HTTP attempt counts.** Initial calls and retries each invoke
  ``record_attempt()`` once before sending the request.
- **Coexistence with RateLimiter.** Check Redis rate limits first; this governor
  only caps total attempts per backfill run.

## Dependencies

None for budget (pure in-memory counter for one run). Partition runners depend on
TikTok analytics resources, ETL transform, and repos.

## Product partition (#467)

- ``backfill_product_partition(session, shop_id, partition_date, resource, budget, ...)``
  — one calendar-day A-34 paginated fetch; upserts ``grain=product`` rows; marks
  ``product`` bucket complete only when every page succeeds.
- Product Impressions/Views deferred (no A-33 fan-out).

## Out of scope

- LIVE/catalog partitions (#468/#469), orchestrator loop (#470)
- Live Partner HTTP client wiring
