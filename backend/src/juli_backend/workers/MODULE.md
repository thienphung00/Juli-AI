# workers

Background workers: Celery task execution, scheduled polling sync, hourly KPI envelope recompute.

**Includes:** TikTok polling (`services/polling/`), webhook receiver (`api/services/webhook/`).

## Hourly KPI envelope recompute, per shop (fast track P61-D, D71.4; was #533)

Celery Beat schedules `juli_backend.shop_kpi_reconcile_fanout` hourly (`crontab(minute=0)`),
which enqueues one `juli_backend.shop_kpi_reconcile` per connected shop past its fast phase
(enumerated like `shop-poll-fanout`, migration 074's definer function). Each shop's task runs
under `with_shop_scope` and routes through `SharedComputeOrchestrator`
(`enqueue_reason="reconcile_hourly"`): bronze → silver → `gold.kpi_envelopes` → flag-gated
Decision scoring. The hourly gap fetch runs for every shop holding its own read credential
(the targeted-fetch executor signs with that shop's credential and merchant id since P61-D);
a shop without one gets an empty plan and its envelope is recomputed from what its
`poll_shop` cycle ingested. No shop id is configured anywhere:
the old `DEMO_REFERENCE_SHOP_ID` beats (`mock-analytics-hourly-reconcile`,
`analytics-backfill-topup`) are deleted. `DEMO_REFERENCE_SHOP_ID` survives only as the public
Demo display binding in `api/routes/demo_analytics.py` (ADR-094).

## Boot env report (fast track P61-D)

`celery_app.py` (worker and beat) and the API lifespan call
`core.config.log_runtime_env_report(process)`: one `runtime_env_missing` WARNING per missing
required variable / flag that is off, never a value. `_skip_if_unconfigured`
(`tasks/shop_ingestion.py`) logs `shop_ingestion_skipped_unconfigured` at WARNING with the
missing names on every skip.

## Status: LEGACY (fast track P53, D62, 2026-10-18)

Marker only — no behaviour changed, nothing moved or deleted (owner-approved audit cleanup,
`juli-audit/backend.md`). `tenant_context_wrapper.py` (`task_with_tenant_context`, ADR-085 d.2) is used by no task; tasks set their shop scope themselves. RLS-adjacent, so kept. `tasks/fujiwa_poll_beat.py` (`fujiwa_poll_cycle`, `shop_id=None`) was deleted by fast track P61-D (D71.4, audit C4) together with the shop-less poll paths only it used.
