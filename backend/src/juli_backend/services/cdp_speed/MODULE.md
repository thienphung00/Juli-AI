# backend/src/juli_backend/services/cdp_speed

## Purpose

CDP **Speed layer** helpers for webhook-driven, OLTP-shaped freshness (ADR-047 A1).
This package plans **bounded Partner fetches** after material webhooks — not full
Fujiwa poll cycles or unbounded analytics fan-out.

## Public API

Import from the package root:

```python
from juli_backend.services.cdp_speed import (
    plan_targeted_fetch,
    TargetedFetchPlan,
    FetchResource,
    run_shared_compute_job,
    SharedComputeJob,
)
```

- ``plan_targeted_fetch(*, shop_id, catalog_id=None, event_type=None, payload_hints=None)``
  → ``TargetedFetchPlan`` — resolves catalog id (directly or via ``event_type`` using
  ``webhook_catalog``), returns **empty** plan for non-material events, otherwise a
  bounded tuple of named ``FetchResource`` entries (endpoint path + ``ProductionReadResources``
  attribute). Testable without live Partner.
- ``TargetedFetchPlan`` — ``catalog_id``, ``shop_id``, ``resources``; ``is_empty`` when
  no fetch is required.
- ``FetchResource`` — ``name``, ``endpoint_path``, ``resource_attr``.
- ``FUJIWA_POLL_RESOURCE_NAMES`` — frozenset of domain poll attrs
  (``orders``, ``products``, ``returns``, ``inventory``) for negative tests vs
  ``_FUJIWA_POLL_STEPS``.
- ``run_shared_compute_job(session, job)`` / ``SharedComputeOrchestrator.run(job)``
  → executes **bronze append → silver upsert → gold envelope write** in order for one
  shop-scoped material trigger (ADR-046 Q4). Accepts ``enqueue_reason``,
  ``TargetedFetchPlan``, and a per-trigger ``idempotency_key``.
- ``webhook_catalog_enqueue_reason(catalog_id)`` → ``webhook_catalog:<id>`` for material dispatch.
- ``job_correlation_token(shop_id, idempotency_key)`` — bounded log/bronze correlation token.
- ``execute_targeted_fetch_to_bronze`` — production fetch boundary via ``targeted_fetch_sync``
  (orders/returns only; no workers imports).
- ``make_targeted_fetch_bronze_handoff`` — Speed-layer adapter that delegates append-only
  persistence to the ETL-owned bronze writer.
- ``SharedComputeJob`` — ``shop_id``, ``shop_key``, ``enqueue_reason`` (``webhook_catalog:<id>`` or
  ``reconcile_hourly``), ``fetch_plan``, ``idempotency_key``, optional ``event_type``.
- ``SharedComputeResult`` — ``bronze_appended``, ``silver_promoted``, ``gold_written``.

## Event → resource matrix (material catalog)

Locked material ids from ``webhook_catalog.MATERIAL_CATALOG_IDS`` (#532 / ADR-038):

| Catalog | Event type | Partner resources (named) |
|---------|------------|---------------------------|
| **#1** | ``ORDER_STATUS_CHANGE`` | ``orders``, ``analytics_shop`` |
| **#2** | ``REVERSE_STATUS_UPDATE`` | ``returns``, ``orders``, ``analytics_shop`` |
| **#5** | ``PRODUCT_STATUS_CHANGE`` | ``products``, ``analytics_shop``, ``analytics_products_list`` |
| **#12** | ``RETURN_STATUS_CHANGE`` | ``returns``, ``analytics_shop`` |
| **#27** | ``INVENTORY_STATUS_CHANGE`` | ``inventory``, ``products``, ``analytics_shop`` |
| **#39** | ``ACTIVITY_STATUS_CHANGE`` | ``promotion_activity`` (from payload hint), ``analytics_shop`` |
| **#67** | ``REFUND_SUCCESS`` | ``returns``, ``orders``, ``analytics_shop`` |
| **#68** | ``INVENTORY_CHANGED`` | ``inventory``, ``analytics_shop`` |

**Analytics scope:** material plans may list shop/list analytics resources for future
bronze tables, but the Shared Compute executor **defers** fetch for domains without
bronze persistence (``analytics``, ``products``, ``inventory``, ``promotion``) and logs
``targeted_fetch_bronze_deferred``. Only ``orders`` and ``returns`` sync through
``targeted_fetch_sync`` into bronze today.

**Forbidden on material path:** ``_FUJIWA_POLL_STEPS`` (all four domain polls),
``run_fujiwa_poll_cycle``, unbounded ``sync_analytics`` A-31–A-39 fan-out. Hourly
Mock reconcile may use a separate gap plan — not this matrix.

## Extending the matrix

1. Add or confirm the webhook in ``services/tiktok/webhook_catalog.py`` (catalog id,
   ETL channel, ``MATERIAL_CATALOG_IDS`` when compute-enqueueing).
2. Add a row to ``_MATERIAL_FETCH_MATRIX`` in ``targeted_fetch_planner.py`` with the
   **minimal** Partner resource keys implicated by the event (reuse keys from
   ``_STATIC_RESOURCES`` or add a resolver like ``promotion_activity``).
3. Add unit tests in ``tests/unit/test_cdp_speed_targeted_fetch_planner.py`` for the
   new catalog id (non-empty bounded plan + negative vs full poll stack).
4. Update this table.

Do **not** wire A2 Batch governors (Postgres I/O budget, fleet defer) through this
planner — batch gap plans live under ``cdp_batch`` (A2).

## Dependencies

- ``juli_backend.services.tiktok.webhook_catalog`` — material classification + event lookup
- ``juli_backend.integrations.tiktok.constants`` — Partner API path constants
- ``juli_backend.services.etl`` — one-writer-owned bronze append facade

## Must not

- Import or invoke ``cdp_batch`` governors or fleet defer knobs
- Import or invoke ``run_fujiwa_poll_cycle``, ``run_fujiwa_material_resource_fetch``,
  or ``_FUJIWA_POLL_STEPS`` on the material Shared Compute path
- Return the full Fujiwa poll quadruple for a single material event
- Expand material analytics to ``sync_analytics`` detail fan-out
