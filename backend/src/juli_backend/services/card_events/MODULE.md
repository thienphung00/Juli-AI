# backend/src/juli_backend/services/card_events

## Purpose

The card journey log `card_events` (ADR-107 "Amendment 2026-10-20" §1-§3, §5;
fast track P60-1a, D70.9; migration 095, model `models/card_events.py`). One
append-only row per stage of a recommendation, from `proposed` to the final
impact reading, so the training data (ADR-115) and the ADR-107 views read one
table. `action_cards`, `workflow_runs`, `impact_readings` and
`run_measurement_finals` keep their live roles; their writers also write the
event.

## Public API

```python
from juli_backend.services import card_events
```

Live writers -- each runs on the caller's session, in the caller's transaction,
inside a SAVEPOINT on Postgres, and **never raises** (a failure is logged as
`card_event_write_failed`); nothing commits:

| Function | Event(s) | Called from |
|---|---|---|
| `record_emissions(session, decisions, *, occurred_at, config)` | `proposed`, `superseded` | `action_cards.persist.emit_scoring_cards`, `onboarding.quick_scan` |
| `record_proposed` / `record_superseded` | one card each | `record_emissions` |
| `record_budget_outcome(session, *, newly_surfaced, expired, now)` | `shown` (first display), `expired` | `action_cards.emission_budget.apply_emission_budget` |
| `record_accepted(session, card, *, approval_id, run_id, ...)` | `accepted` (per approval) | `agent.approval.approve_action_card` |
| `record_dismissed(session, card, *, occurred_at, ...)` | `dismissed` (`reason_code='unspecified'`) | `POST /v1/demo/decisions/{id}/reject` |
| `record_run_outcome(session, run, *, status, stop_reason, ...)` | `executed` / `not_executed` / `reverted` | runner `conversation_store.persist`, crash handler, reaper sink, `lever_flows.end_wait_by_seller` |
| `record_impact_readings(session, *, run_id, kind, occurred_at)` | `impact_preliminary` / `impact_final` | `workers/impact_reader/pipeline._process_kind` |
| `record_measurement_final(session, row)` | `impact_final` | `lever_flows.measurement`, `content_cards.measurement` |
| `natural.record_seller_change(session, external_change)` | `seller_change` (P60-1b) | `product_history.store.record_change` (every product change not entirely Juli's, any shop) |

Backfill: `backfill_shop(session, shop_id) -> BackfillReport` (per-event
`considered` / `inserted`), including `seller_change` for every past
`external_changes` row not entirely Juli's (`natural.seller_change_specs`). Run
by the manual Celery tasks `juli_backend.card_events_backfill(shop_id)` and
`juli_backend.card_events_backfill_fanout()` (`workers/tasks/card_events_backfill.py`,
not on beat). The fan-out reaches every shop with cards, Juli writes or observed
changes -- connected or not -- through migration 096's `enumerate_history_shops()`
(SECURITY DEFINER, ids only), plus every pollable shop.

`seller_change` (amendment §8): `card_id` = the card whose run last wrote one of
the change's non-Juli fields, else the card whose plan window is open on the
product (its latest executed run completed less than `OPEN_PLAN_WINDOW` = 14 days
before the change), else NULL (a natural action, `workflow_key = 'natural'`).
`payload.attribution` is `seller_revert` when every non-Juli field is a revert,
else `seller_change`; `payload.field_attribution`, `fields`, `external_change_id`,
`card_link` (`last_write` / `open_window` / null). Key `seller_change:<change id>`.

Lower level: `EventSpec`, `insert_event(session, spec) -> bool` (`INSERT ... ON
CONFLICT DO NOTHING`; raises on a database error).

## Invariants

- **Idempotent.** Every row has a deterministic `dedup_key` (`keys.py`) shared
  by the live writer and the backfill; unique (`shop_id`, `dedup_key`). Events
  that happen once per card (`proposed`, `shown`, `dismissed`, `expired`,
  `seller_done`, `superseded`) are also unique per (`card_id`, `event_type`).
  `accepted` is once per approval and `executed` / `not_executed` / impact once
  per run: a failed run puts the card back on the desk (D47.5), so a card can
  be approved and run more than once.
- **Append-only.** `juli_app` has SELECT / INSERT only; a correction is a new event.
- **Tenant-scoped.** Writers run under the shop's scope (request, or
  `with_shop_scope` in fleet jobs, ADR-089); RLS refuses a row for another shop.
- **Outcome mapping** (`outcomes.py`, ADR-107 decision 6): `executed` = status
  `completed` with `final_response`; everything else terminal is `not_executed`
  with its `stop_reason` and a derived group. A finished revert run writes
  `reverted` on the original card instead; a failed revert writes nothing.
- **Subject.** `subject_id` is the TikTok product id for a product card (the
  card's own `subject_id`, a `products.id`, is kept in `payload.card_subject_id`).

## Not here yet (DEBT P60-1a)

`edited`, `seller_done`, `shadow` (ADR-115); `readiness_level` (ADR-112 D3 levels) and
`feature_snapshot_id` (P60-1e) stay NULL; the measurement plan of decision 7.

## Dependencies

`models.card_events`, `models.models` (ActionCard, WorkflowRun, Product,
ImpactReading, ...), `models.lever_flows`, `models.decision_reasons`,
`services.action_cards.subjects`.
