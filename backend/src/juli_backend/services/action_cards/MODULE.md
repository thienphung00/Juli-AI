# backend/src/juli_backend/services/action_cards

## Purpose

Manual-refresh pipeline persistence for **Decision** rows (Action Cards per
`CONTEXT.md` and ADR-021). Poll (optional) → scoring → Postgres upsert.

## Public API

- `run_action_card_refresh(session, shop_id, *, poll=True)` → `list[ActionCard]`
- `persist_scoring_result(session, shop_id, result)` → `list[ActionCard]`
- `maybe_poll_tiktok_data(session, shop_id)` — Fujiwa poll when `TIKTOK_APP_*` set
- `enqueue_action_card_refresh(session, *, shop_id)` → Celery task id

## HTTP (via `api/routes/action_cards.py`)

- `POST /v1/action-cards/refresh` — 202 Accepted, enqueues Celery task
- `GET /v1/action-cards` — persisted active cards only (no regeneration)

## Dependencies

- `juli_backend.services.scoring.pipeline` — `run_daily_scoring_for_shop` (unchanged)
- `juli_backend.repositories.repos.ActionCardsRepo` — idempotent `(shop_id, workflow_key)` upsert
- `juli_backend.workers.services.polling` — optional Fujiwa poll before scoring
- `juli_backend.workers.tasks.action_card_refresh` — Celery entrypoint

## Key behaviors

- Unique constraint on `(shop_id, workflow_key)` — re-refresh updates rows in place
- No Redis; Postgres is the sole store (ADR-021)
- HTTP handlers never run scoring inline — same pattern as `execution/dispatch.py`
- `DAILY_SCORING_CRON_UTC` remains unused (manual refresh only)
- Analytics-backed CTR (#428) ranks mid/large Ads workflows (`create_activity_7a`,
  `update_activity_7c`) through unchanged `run_action_card_refresh` →
  `persist_scoring_result`; ROAS/CAC cards appear only when spend ETL supplies denominators
- List API freshness: `metadata.computed_at` (scoring run) and `updated_at` (row bump);
  `recommendation.computed_at` duplicates the same timestamp — no separate envelope field (#429)

## Out of scope

- Celery beat / scheduled scoring
- Redis read-through cache
- Seller-facing "Decision" UI (`web/`)
