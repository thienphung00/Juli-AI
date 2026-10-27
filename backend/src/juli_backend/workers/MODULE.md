# workers

Background workers: Celery task execution, scheduled polling sync.

**Includes:** TikTok polling (`services/polling/`), webhook receiver (`api/services/webhook/`).

## Retired: the reference-shop KPI beats (fast track P61-D, owner D72.5, 2026-10-21)

`mock-analytics-hourly-reconcile` (#533, ADR-038 §5) and `analytics-backfill-topup` (#791)
recomputed / topped up ONE shop (`DEMO_REFERENCE_SHOP_ID`) for the public
`GET /v1/demo/analytics` envelope, which apps/demo no longer reads. Route (now 410 Gone),
beats, tasks and the env read are gone (Supabase egress). Every shop's analytics lands through
its own `poll_shop` cycle; no worker reads `DEMO_REFERENCE_SHOP_ID`.

## Stored errors carry no data (D16, 2026-10-27)

`shop_ingestion_state.last_error` and `tiktok_sync_state.last_error` (and the
`poll_step_outcome` / `shop_bootstrap_failed` log fields) hold
`core.privacy.error_label(exc)` -- the class and the vendor's numeric code
(`TikTokAPIError code=105001`) -- never `repr(exc)`, which can echo a vendor body or
the buyer data a validator rejected. Worker engines set `hide_parameters=True`
(`database.ENGINE_DEFAULTS`). `tests/unit/test_no_raw_buyer_stores.py` fails on a new
`repr(exc)` into a `last_error`; older rows are relabelled by
`services/privacy/payload_cleanup`.

## Boot env report (fast track P61-D)

`celery_app.py` (worker and beat) and the API lifespan call
`core.config.log_runtime_env_report(process)`: one `runtime_env_missing` WARNING per missing
required variable / flag that is off, never a value. `_skip_if_unconfigured`
(`tasks/shop_ingestion.py`) logs `shop_ingestion_skipped_unconfigured` at WARNING with the
missing names on every skip.

## Status: LEGACY (fast track P53, D62, 2026-10-18)

Marker only — no behaviour changed, nothing moved or deleted (owner-approved audit cleanup,
`juli-audit/backend.md`). `tenant_context_wrapper.py` (`task_with_tenant_context`, ADR-085 d.2) is used by no task; tasks set their shop scope themselves. RLS-adjacent, so kept. `tasks/fujiwa_poll_beat.py` (`fujiwa_poll_cycle`, `shop_id=None`) was deleted by fast track P61-D (D71.4, audit C4) together with the shop-less poll paths only it used.

## Worker database connections (fast track P62-B, D72.4 -- not changed)

`database.ensure_worker_session_factory` builds one engine per process with `NullPool`
(#871): every Celery task enters through `asyncio.run()`, i.e. a fresh event loop, and a
pooled asyncpg connection is bound to the loop that opened it ("Future attached to a
different loop"). So each worker *session* opens a new pooler connection (TCP + TLS +
Supavisor auth -> `pgbouncer.get_auth`, then `DISCARD ALL` on close). `DATABASE_URL` is the
Supavisor SESSION pooler (port 5432, ADR-086): prepared statements and a client-side pool
would be safe there; the transaction pooler (6543) would need `statement_cache_size=0`.
A pooled worker engine needs a per-process persistent event loop for every task (21 task
modules call `asyncio.run`) -- deliberately not done in P62-B (owner, 2026-10-21: skip if
risky before the cycle reset); see fasttrack/DEBT.md.

`processed_events_retention` (nightly 20:34 UTC): D72.2, see `services/etl/MODULE.md`.
