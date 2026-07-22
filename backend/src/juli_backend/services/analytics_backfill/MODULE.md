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

## Caller contract

- **Budget exhaust ≠ partition complete.** When ``finish("budget")`` or
  ``should_stop()`` triggers a clean pause, the orchestrator must **not** call
  partition ``mark_complete`` for the in-flight partition. Resume on the next run.
- **Each HTTP attempt counts.** Initial calls and retries each invoke
  ``record_attempt()`` once before sending the request.
- **Coexistence with RateLimiter.** Check Redis rate limits first; this governor
  only caps total attempts per backfill run.

## Dependencies

None (pure in-memory counter for one run).

## Out of scope

- Partition progress table (#464), schema columns (#463)
- ETL mappers, orchestrator loop (#466–#470)
- Live Partner HTTP client wiring
