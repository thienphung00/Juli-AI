# workers

Background workers: Celery task execution, scheduled polling sync.

**Includes:** TikTok polling (`services/polling/`), webhook receiver (`api/services/webhook/`).

## Retired: the reference-shop KPI beats (fast track P61-D, owner D72.5, 2026-10-21)

`mock-analytics-hourly-reconcile` (#533, ADR-038 §5) and `analytics-backfill-topup` (#791)
recomputed / topped up ONE shop (`DEMO_REFERENCE_SHOP_ID`) for the public
`GET /v1/demo/analytics` envelope, which apps/demo no longer reads. Route (now 410 Gone),
beats, tasks and the env read are gone (Supabase egress). Every shop's analytics lands through
its own `poll_shop` cycle; no worker reads `DEMO_REFERENCE_SHOP_ID`.

## Boot env report (fast track P61-D)

`celery_app.py` (worker and beat) and the API lifespan call
`core.config.log_runtime_env_report(process)`: one `runtime_env_missing` WARNING per missing
required variable / flag that is off, never a value. `_skip_if_unconfigured`
(`tasks/shop_ingestion.py`) logs `shop_ingestion_skipped_unconfigured` at WARNING with the
missing names on every skip.

## Status: LEGACY (fast track P53, D62, 2026-10-18)

Marker only — no behaviour changed, nothing moved or deleted (owner-approved audit cleanup,
`juli-audit/backend.md`). `tenant_context_wrapper.py` (`task_with_tenant_context`, ADR-085 d.2) is used by no task; tasks set their shop scope themselves. RLS-adjacent, so kept. `tasks/fujiwa_poll_beat.py` (`fujiwa_poll_cycle`, `shop_id=None`) was deleted by fast track P61-D (D71.4, audit C4) together with the shop-less poll paths only it used.
