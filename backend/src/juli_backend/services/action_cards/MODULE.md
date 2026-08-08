# backend/src/juli_backend/services/action_cards

## Purpose

Manual-refresh pipeline persistence for **Decision** rows (Action Cards per
`CONTEXT.md` and ADR-021). Poll (optional) → scoring → Postgres upsert.
`persist_scoring_result` is also the durability boundary for **continuous**
scoring candidates on compute (#715, B-3) — idempotent, status-preserving,
and freshness-stamped so it is safe for a webhook-driven or hourly-reconcile
scoring stage to call repeatedly for the same shop without corrupting
in-flight card state. (Wiring a continuous compute trigger's scoring stage
— e.g. `cdp_speed.decision_rules_scoring_stage` — onto this function is not
owned by this module; see `services/cdp_speed/MODULE.md`.)

## Public API

- `run_action_card_refresh(session, shop_id, *, poll=True)` → `list[ActionCard]`
- `persist_scoring_result(session, shop_id, result)` → `list[ActionCard]`
- `IN_FLIGHT_STATUSES` — `frozenset[str]` (`approved`, `dismissed`, `executing`)
  — statuses `persist_scoring_result` will not overwrite on re-scoring (#715)
- `persist_legacy_recommendations(session, shop_id)` → `None` — sole write owner
  for retained `recommendations` rows (legacy GET /v1/recommendations refresh path)
- `maybe_poll_tiktok_data(session, shop_id)` — Fujiwa poll when `TIKTOK_APP_*` set
- `enqueue_action_card_refresh(session, *, shop_id)` → Celery task id

## HTTP (via `api/routes/action_cards.py`)

- `POST /v1/action-cards/refresh` — 202 Accepted, enqueues Celery task
- `GET /v1/action-cards` — persisted active cards only (no regeneration)

## Dependencies

- `juli_backend.services.scoring.pipeline` — `run_daily_scoring_for_shop` (unchanged)
- `juli_backend.repositories.repos.ActionCardsRepo` — idempotent `(shop_id, workflow_key)` upsert
- `juli_backend.workers.services.polling` — optional Fujiwa poll before scoring
- Celery enqueue via injectable `RefreshDispatcher` — production adapter in
  `juli_backend.workers.dispatch_binding` (bound at API/worker startup; #554)

## Key behaviors

- Unique constraint on `(shop_id, workflow_key)` — re-refresh updates rows in place
- Sole write owner for `action_cards` and retained legacy `recommendations` tables
- No Redis; Postgres is the sole store (ADR-021)
- HTTP handlers never run scoring inline — same pattern as `execution/dispatch.py`
- `DAILY_SCORING_CRON_UTC` remains unused (manual refresh only)
- Analytics-backed CTR (#428) ranks mid/large Ads workflows (`create_activity_7a`,
  `update_activity_7c`) through unchanged `run_action_card_refresh` →
  `persist_scoring_result`; ROAS/CAC cards appear only when spend ETL supplies denominators
- List API freshness: `metadata.computed_at` (scoring run) and `updated_at` (row bump);
  `recommendation.computed_at` duplicates the same timestamp — no separate envelope field (#429)
- **Freshness column (#715, B-3, ADR-038):** `ActionCard.computed_at` (nullable
  `DateTime(timezone=True)`, migration `026_action_cards_computed_at`) carries the
  scoring run's `ScoringSignals.computed_at` on a real, queryable column — the
  same "when did this compute run finish" semantics as `GoldKpiEnvelope.computed_at`
  / `AnalyticsKpiEnvelope.computed_at` — in addition to the pre-existing
  `metadata.computed_at` / `recommendation.computed_at` JSON copies (kept for
  backward-compatible reads; #429). A dedicated "promotion"/`surfaced_at`
  timestamp is **not** added here — that is B-4's (#716) emission/surfacing
  budget; `updated_at` (bumped on every non-suppressed upsert) stands in as the
  persisted-at signal until B-4 lands a surfacing-specific column.
- **Idempotent-upsert + status-preservation (#715, B-3):** `persist_scoring_result`
  looks up the existing `(shop_id, workflow_key)` row *before* delegating to
  `ActionCardsRepo.upsert`. If the existing row's `status` is in
  `IN_FLIGHT_STATUSES` (`approved` / `dismissed` / `executing`), the row is
  left completely untouched — no status, content, or `computed_at` change —
  and the untouched card is still included in the returned list so callers see
  the full candidate set for the run. Only a card still in the `"active"`
  candidate status (or not yet persisted) is upserted. This preserves seller
  (or dry-run) decisions across continuous re-scoring without a second
  surfacing-state model living in this module.
- **Negative-path / atomicity:** `persist_scoring_result` performs no `commit`
  itself (same as before) — a caller wrapping the call in a transaction that
  rolls back on failure (e.g. the Shared Compute Orchestrator's isolated
  scoring failure domain, #713) leaves previously-committed cards exactly as
  they were; a failure partway through one run's recommendation loop leaves no
  partial row from that run visible after rollback.

## Out of scope

- Celery beat / scheduled scoring
- Redis read-through cache
- Seller-facing "Decision" UI (`web/`)
- Decision emission/surfacing budget (active cap, cooldown, novelty quota) — #716, B-4
- Public Decision read API — #718, B-6
