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

`processed_events_retention` (nightly 20:37 UTC): D72.2, see `services/etl/MODULE.md`.
