# backend/src/juli_backend/services/cdp_batch

## Purpose

Phase 3.5-A2 **Batch layer** modules — OLAP-shaped fleet throughput on the CDP
medallion spine ([ADR-047](../../../docs/adr/047-cdp-lambda-layers-prd-split.md),
[ADR-048](../../../docs/adr/048-cdp-webhook-first-spine-dual-credential.md)).
Orthogonal to A1 Speed; writes the same `gold.kpi_envelopes` via Shared Compute
(deferred slices).

## Public API

### StaggerScheduler (#615)

- ``window_minute_for_shop(shop_id)`` → ``int`` in ``[0, 1439]`` — stable
  SHA-256 hash of ``shop_id`` (not Python ``hash()``)
- ``assign_window(shop_id, day)`` → ``ReconcileWindow`` — one reconcile slot
  per shop per UTC calendar day; ``minute_of_day`` is invariant to ``day``
- ``StaggerScheduler.assign_window(shop_id, day)`` — class wrapper for callers
  that inject scheduler dependencies later

``ReconcileWindow`` fields: ``shop_id``, ``day`` (UTC date), ``minute_of_day``.

### PartnerApiBudgetGovernor (#616)

Per-run Partner HTTP attempt caps for batch reconcile. Wraps
``analytics_backfill.budget.CallBudgetGovernor`` (ADR-029 400/499 soft/hard
pattern) with batch-facing ``try_consume`` / ``finish``.

- ``begin_partner_budget_run(max_attempts=400, hard_limit=499)`` → fresh governor
- ``try_consume()`` → ``True`` under hard cap; ``False`` when hard cap reached
- ``should_defer()`` → ``True`` once soft target reached (orchestrator should defer)
- ``record_success`` / ``record_failure`` / ``record_rate_limited`` — outcome counters
- ``finish("partner_budget_exhausted")`` → structured logs; partition **not** complete
- ``finish("complete")`` → ``implies_partition_complete`` is ``True``
- ``DEFER_REASON`` — constant ``"partner_budget_exhausted"``

Structured log fields: ``attempts``, ``successes``, ``failures``, ``rate_limited``,
``stopped_reason``, ``defer_reason``. Never logs tokens or PII.

Orthogonal to ``PostgresIoBudgetGovernor`` (#617) — dual budgets, separate modules.

### ShopComputeMutex (#618)

Shared Redis mutex between batch and speed Shared Compute paths. Key pattern
``compute:{shop_id}`` with ``COMPUTE_MUTEX_TTL_SECONDS`` (600s default). **Not**
the ETL ingest ``material_analytics:mutex:*`` gate or per-shop asyncio backpressure.

- ``compute_mutex_key(shop_id)`` → Redis key string
- ``try_begin_batch_compute(mutex, shop_id)`` → ``BatchComputeEntryResult`` —
  defers with ``speed_mutex_active`` when speed holds the lock; acquires batch
  ownership when free
- ``ShopComputeMutex.try_acquire(shop_id, owner)`` / ``release(shop_id, owner)``
  — ``owner`` is ``"speed"`` or ``"batch"`` (speed wiring is A1; API published here)
- ``InMemoryShopComputeMutex`` / ``RedisShopComputeMutex`` — test and production backends
- ``RedisShopComputeMutex`` uses atomic Lua compare-and-delete / compare-and-expire so
  stale release or same-owner refresh cannot clobber a new owner after TTL rollover
- ``SPEED_MUTEX_DEFER_REASON`` (package export) — constant ``"speed_mutex_active"``

Structured log fields on defer: ``defer_reason``, ``stopped_reason``.

### BatchFetchPlanner (#619)

Gap-gated bounded Partner fetch plans for daily batch reconcile. Broader than
A1 ``plan_targeted_fetch`` (webhook-first material triggers) but still capped —
no full Fujiwa poll quadruple or unbounded ``sync_analytics`` A-31–A-39 fan-out.

**Boundary vs A1 targeted fetch:** A1 owns webhook-first targeted plans under
``cdp_speed/targeted_fetch_planner.py`` (material catalog id → minimal resources).
BatchFetchPlanner owns **gap-detected reconcile** for stagger-scheduled fleet
windows — domain gaps (orders/products/returns/inventory) plus speed-deferred
P1 batch fetches (``finance_statements``, ``analytics_videos``). Do not duplicate
A1 material-path plans; batch orchestrator calls this module only from scheduled
reconcile entrypoints.

- ``plan_batch_fetch(*, shop_id, detected_gaps, reconcile_window=None, trigger_source="batch_reconcile")``
  → ``BatchFetchPlan`` — empty resources + ``defer_reason="gap_not_detected"`` when
  ``detected_gaps`` is empty (does not pull 3.5-C cold-start fleet scope)
- ``BatchFetchPlanner.plan(...)`` — class wrapper for orchestrator injection
- ``BatchFetchPlan`` — ``shop_id``, ``resources``, optional ``defer_reason``,
  ``reconcile_window`` (from ``StaggerScheduler``); ``should_fetch`` when resources
  present and not deferred
- ``BatchFetchResource`` — ``name``, ``endpoint_path``, ``resource_attr``, ``params``
- ``is_batch_fetch_trigger_allowed(trigger_source)`` — guard for PRD US #25; rejects
  ``fake_refresh``, ``demo_public``, ``visitor_refresh``, ``public_demo``
- ``FORBIDDEN_TRIGGER_SOURCES`` — frozenset documented for orchestrator guards
- ``DOMAIN_GAP_KINDS`` / ``P1_DEFERRED_GAP_KINDS`` — allowed gap fixture keys
- ``MAX_BATCH_RESOURCES`` — hard cap (8) on plan size

Structured defer: ``gap_not_detected`` when no gap requires fetch. Fake Refresh /
public Demo traffic must **not** invoke the planner — use
``is_batch_fetch_trigger_allowed`` before calling ``plan_batch_fetch``.

### Deferred (later A2 slices)

- ``PostgresIoBudgetGovernor`` — bronze/silver I/O throttle (#617)
- ``BatchReconcileOrchestrator`` — shop-scoped fetch → Shared Compute → gold

## Scheduler deployment

**Celery Beat / periodic ``is_due`` is deferred** — this slice only defines
deterministic assignment math. A future orchestrator will poll
``assign_window(shop_id, today)`` and enqueue when the current UTC minute
matches ``minute_of_day``. Mechanism is flexible; determinism is not.

## Out of scope (#615)

- Hourly Fujiwa exception (remains **A1 Speed** per ADR-048)
- Partner API calls, Postgres fleet queries, Redis mutex
- ``is_due`` slot runner, Celery Beat schedule wiring
- Postgres I/O governor (#617) and batch orchestrator (CDP-A2-3+)

## Dependencies

Pure in-memory; no I/O. Safe for PR CI without live credentials.

## Tests

- ``tests/unit/test_cdp_batch_stagger_scheduler.py`` — stability, range,
  collision-free stub fleet (100 shops), spread across 1440 minutes.
- ``tests/unit/test_cdp_batch_partner_budget.py`` — soft/hard cap defer,
  under-cap consume, structured log fields; no live Partner HTTP.
- ``tests/unit/test_cdp_batch_shop_compute_mutex.py`` — batch defer on
  ``speed_mutex_active``, contention with speed owner, last-good gold unchanged;
  InMemory + FakeSyncRedis only.
- ``tests/unit/test_cdp_batch_fetch_planner.py`` — gap-gated bounded plans,
  ``gap_not_detected`` defer, P1 finance/video sequencing, A1 boundary negative
  tests, Fake Refresh guard; no live Partner HTTP.
