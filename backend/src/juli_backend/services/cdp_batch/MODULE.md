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

### Deferred (later A2 slices)

- ``BatchFetchPlanner`` — event/gap → bounded Partner resource list
- ``PartnerApiBudgetGovernor`` — per-credential Partner call caps (#616)
- ``PostgresIoBudgetGovernor`` — bronze/silver I/O throttle (#617)
- ``ShopComputeMutex`` — defer when speed compute active
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
- Budget governors and batch orchestrator (CDP-A2-2+)

## Dependencies

Pure in-memory; no I/O. Safe for PR CI without live credentials.

## Tests

``tests/unit/test_cdp_batch_stagger_scheduler.py`` — stability, range,
collision-free stub fleet (100 shops), spread across 1440 minutes.
