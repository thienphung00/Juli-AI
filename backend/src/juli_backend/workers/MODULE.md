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

## Status: LEGACY (fast track P53, D62, 2026-10-18)

Marker only — no behaviour changed, nothing moved or deleted (owner-approved audit cleanup,
`juli-audit/backend.md`). `tenant_context_wrapper.py` (`task_with_tenant_context`, ADR-085 d.2) is used by no task; tasks set their shop scope themselves. RLS-adjacent, so kept. `tasks/fujiwa_poll_beat.py` (`fujiwa_poll_cycle`) is registered but on no beat since `shop_poll_fanout` replaced it; deleting it (audit C4) waits for the fan-out to be proven in production (DEBT).
