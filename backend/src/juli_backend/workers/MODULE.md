# workers

Background workers: Celery task execution, scheduled polling sync, Phase 2.10 Mock reconciler.

**Includes:** TikTok polling (`services/polling/`), webhook receiver (`api/services/webhook/`).

## Mock-mode hourly reconciler (#533, ADR-038 §5)

Celery Beat schedules `juli_backend.mock_analytics_hourly_reconcile` hourly
(`crontab(minute=0)`). The job recomputes Analytics KPI envelopes for
`DEMO_REFERENCE_SHOP_ID` only — not a global daily scoring cron and not a
fan-out across all shops.

Implementation reuses `material_analytics_precompute_sync` (#532) so hourly
reconciliation is idempotent with material-webhook compute (Postgres upsert +
Redis cache refresh).
