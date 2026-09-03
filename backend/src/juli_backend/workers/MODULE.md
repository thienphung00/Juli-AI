# workers

Background workers: Celery task execution, scheduled polling sync, Phase 2.10 Mock reconciler.

**Includes:** TikTok polling (`services/polling/`), webhook receiver (`api/services/webhook/`).

## Mock-mode hourly reconciler (#533, ADR-038 §5)

Celery Beat schedules `juli_backend.mock_analytics_hourly_reconcile` hourly
(`crontab(minute=0)`). The job recomputes Analytics KPI envelopes for
`DEMO_REFERENCE_SHOP_ID` only — not a global daily scoring cron and not a
fan-out across all shops.

It needs **both** `DEMO_REFERENCE_SHOP_ID` and `DEMO_REFERENCE_SHOP_KEY`. The
key is configuration rather than a database lookup (#1518): `public.shops` is
keyed on `user_id = app_current_user_id()`, and this task has a shop but no
user, so once the runtime connects as `juli_app` that read returns zero rows.
Reading it would leave the task skipping silently; with the key configured it
does its work and, if the key is missing, skips with an explicit
`missing_demo_reference_shop_key` reason instead.

Implementation reuses `material_analytics_precompute_sync` (#532) so hourly
reconciliation is idempotent with material-webhook compute (Postgres upsert +
Redis cache refresh).
