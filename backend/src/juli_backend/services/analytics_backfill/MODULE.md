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
- ``generate_coverage_report(session, shop_id=..., end_date=..., start_date=...)`` →
  ``CoverageReport`` — Phase 2.9 exit coverage (#471)
- ``meets_coverage_threshold(days_present, days_total, threshold)`` — exact fraction
  gate (``days_present / days_total >= threshold``; no rounding before compare)
- ``coverage_report_to_json(report)`` / ``coverage_report_to_markdown(report)`` —
  operator-facing report serializers

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

## Operator command (#471)

Coverage report (requires ``DATABASE_URL``; exit code 0 when ``exit_ready``):

```bash
cd backend
PYTHONPATH=src DATABASE_URL="$DATABASE_URL" \
  python -m juli_backend.services.analytics_backfill.cli coverage \
  --shop-id "<shop-uuid>" \
  --start 2026-03-16 \
  --end 2026-07-21 \
  --output /tmp/analytics-coverage.json
```

Thresholds (ADR-029): combined Revenue (A-36) **and** LIVE overview (A-29-derived)
≥ **95%** of calendar days; Product list (A-34) ≥ **90%**. Rounding: ``coverage_pct``
is displayed to one decimal; gate uses exact fraction ``qualifying_days / total_days
>= threshold`` (e.g. 949/1000 fails, 950/1000 passes at 95%).

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

## Concurrency (#795)

``backfill_analytics_history(..., concurrency_limit=N)`` runs up to N partitions'
**fetch** phase truly in parallel via ``asyncio.to_thread`` — the four partition
runners (``backfill_revenue_partition``, ``backfill_product_partition``,
``run_live_partition``, ``run_catalog_partition``) all offload their blocking
vendor-client calls off the event-loop thread. DB touches (``is_complete``,
``upsert``, ``mark_complete``/``mark_failed``) stay serialized: every runner
accepts an optional ``session_lock: asyncio.Lock | None`` and every caller
sharing ONE ``AsyncSession`` across concurrent partitions **must** pass the
same lock instance, or two tasks can corrupt that session (SQLAlchemy does not
support concurrent use of one ``AsyncSession``).

``backfill_analytics_history_auto_topup`` (the scheduled Celery Beat caller) is
the reference wiring: it builds one ``session_lock`` and threads it through all
four partition-runner calls, and resolves ``concurrency_limit`` from the
``ANALYTICS_BACKFILL_CONCURRENCY_LIMIT`` env var (default
``DEFAULT_AUTO_TOPUP_CONCURRENCY_LIMIT = 4``). Raising this does not increase
Partner load or risk ADR-029's ``hard_limit=499`` — the Redis-backed
``RateLimiter`` governs actual call rate, and ``budget_lock`` inside
``backfill_analytics_history`` keeps the hard limit race-free under
concurrency; more in-flight tasks just finish the same capped call budget
sooner. Callers with a per-partition session (or no shared session at all) may
omit ``session_lock`` — it defaults to no locking.

## Out of scope

- HITL operator tooling (#472)
- Live Partner HTTP client wiring in unit tests
