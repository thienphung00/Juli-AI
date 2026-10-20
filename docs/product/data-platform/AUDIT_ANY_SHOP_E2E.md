# Audit — any shop end to end, hardcodes, streaming (2026-10-20, branch @ 4a598bc9)

Read-only audit by an agent (Sonnet); the blocker (A1) was re-checked by the lead. Paths are
under `backend/src/juli_backend/` unless they start with `tests/`, `apps/`, `infra/`. Decision:
D71; work: P61.

**Headline.** Ingestion is per shop (connect → bootstrap → poll → diagnosis → cards →
`card_events`). Agent reads, agent writes, measurement and LLM streaming were not ready for a
second shop.

## A. Hardcodes on production paths

| # | Item | Where | Status | P61 |
|---|---|---|---|---|
| A1 | Agent read for every non-sandbox shop uses the Fujiwa credential + `PRODUCTION_AUTH_ID` (also content runs, product info) | `services/agent/composition.py:266-275`; `workers/tasks/agent_workflow.py:490`; `workers/tasks/content_runs.py:55`; `services/content_analysis/product_info.py:80` | **Gap, blocker** (wrong shop's catalogue) | A |
| A2 | Agent write bound to the sandbox merchant; production leg of `listing_handlers.py` returns a marker only | `services/agent/composition.py:280-296`; `services/execution/listing_handlers.py:75-90`; `services/execution/production_write_resolver.py:86` | Gated by design (P5 not started) | B |
| A3 | `PRODUCTION_AUTH_ID` / `SANDBOX_AUTH_ID` default to literal merchant ids | `integrations/tiktok/merchant.py:56-57` | Gap (fail closed instead) | D |
| A4 | `PRODUCTION_AUTH_ID` passed for a shop-scoped backfill | `services/analytics_backfill/orchestrator.py:626` | Latent gap | A |
| A5 | `DEMO_REFERENCE_SHOP_ID` daily top-up + hourly mock reconcile beats | `workers/tasks/analytics_backfill_topup.py:35,143`; `workers/tasks/mock_analytics_reconcile.py:61`; `workers/celery_app.py:58,72` | Gap (other shops' KPI envelope not recomputed hourly) | D |
| A6 | Dead `fujiwa_poll_beat` (`shop_id=None`) and stale docs | `workers/tasks/fujiwa_poll_beat.py`; `workers/tasks/impact_reader.py:8-15`; `workers/MODULE.md:11`; `infra/scripts/restore-analytics-history.sh:20,58-59` | Cleanup | D |
| A7 | `AGENT_WORKFLOWS_ENABLED=false` in the env example; bootstrap silently skips without `TIKTOK_APP_KEY` / `TIKTOK_APP_SECRET` / `TIKTOK_REDIRECT_URI` / `REDIS_URL` | `infra/scripts/env/api.env.example:95`; `workers/tasks/shop_ingestion.py:620` | Verify production; make it loud | D + owner |
| — | Kept on purpose: public demo display binding `api/routes/demo_analytics.py:33` (ADR-094), `CDP_ENABLED_WORKFLOWS` (D24), reviewer / demo seed ids | — | OK | — |

## B. New-shop journey

| Step | Entry | Status |
|---|---|---|
| OAuth callback, credential, shop row | `services/tiktok/oauth.py:224` `_after_connect_committed`; `provision_shop_and_credentials` | OK, no allowlist |
| Bootstrap + fan-out | `bootstrap_shop` (`ingest_priority`); beat `shop-poll-fanout`; `enumerate_pollable_shops` | OK |
| History, analytics, diagnosis, quick scan, cards | `shop_history_backfill`, `poll_shop`, `shop_diagnosis_daily/job.py`, `quick_scan.py`, `run_action_card_refresh` | OK, per shop |
| Approve | `approve_action_card` → `_enqueue_run_agent_workflow` | Needs `AGENT_WORKFLOWS_ENABLED`; optimize-product playbook only (deliberate 409 otherwise) |
| Run reads | `composition.py:266` | **Gap A1** |
| Execute | `resolve_write_capability` + ADR-085 gates | Production leg is a stub → sandbox write reported as success (**gap: honest UX**) |
| Measure | beat `daily-impact-reader` | Keyed per shop; reads sandbox executions against real analytics until P5 |
| `card_events` | P60-1a writers | OK; live `shown` / `expired` not wired |
| Reject card | — | **Gap**: no backend route (DEBT P7-C) |

## C. End-to-end test coverage

Two-tenant slices exist (`tests/integration/test_shop_ingestion_two_tenant.py`,
`test_impact_reader_two_tenant.py`, `test_card_events_db.py`, `test_run_changes_two_tenant.py`,
`test_shop_diagnosis_two_tenant.py`, `test_ingest_two_tenant.py`, …), plus sandbox
`test_outcome_chain_postgres.py` and Playwright with stubbed routes. **Missing:** one chained test
OAuth → bootstrap → cards → approve → run → execute → measure → `card_events` for a non-reference
shop; a test that shop B's agent run never reads shop A; production-leg execution; token streaming.

## D. LLM streaming

| Surface | Where | Status |
|---|---|---|
| Agent adapter | `services/agent/llm/openai_adapter.py:24,233` (`"stream": False`); `blocks.py:64` | **Gap** — whole turn only; `assistant.text.delta` reserved by ADR-071 d.3 |
| Run events SSE | `api/routes/agent_runs.py:139-184`; `services/agent_runs/events.py` | OK (replay, Last-Event-ID) |
| UI consumer | `apps/demo/src/lib/agent-event-stream.ts` (rejects the delta at L300), `lib/run-surface/use-run-stream.ts`, `reduce-run-view.ts` | Whole block; no caret |
| Card drafts, media analysis, vision | `services/content_cards/drafter.py`; `services/content_analysis/openai_media.py`; `services/agent/vision.py` | Non-streamed by design (structured) |
| Model | `services/agent/llm/config.py:18` `gpt-5.4-nano` (`LLM_MODEL`) | OK |
