# backend/src/juli_backend/services/demo_decisions

## Purpose

Public Demo Decisions **read** service (#718, B-6, ADR-037 Demo no-auth /
ADR-038) — the query + masking layer behind
`GET /v1/demo/decisions` (list) and `GET /v1/demo/decisions/{id}` (detail).
This is the read counterpart to `services/demo_execution` (#717, B-5, the
approve → dry-run write path) and consumes, but never mutates, persistence
owned by #715 (B-3, `services/action_cards/persist.py`) and #716 (B-4,
`services/action_cards/emission_budget.py`).

"Emission-gated" means `ActionCard.surfaced_at`-gated: a candidate the
emission budget most recently *suppressed* (or never evaluated) is excluded
from both the list and detail lookup — not returned, and not distinguishable
from a nonexistent row when looked up by id (safe-default 404).

## Public API

- `list_surfaced_decisions(session, shop_id) -> list[ActionCard]` — the
  emission-gated active set (`status == "active"` and `surfaced_at IS NOT
  NULL`) for *shop_id*, ranked `priority` asc, `surfaced_at` desc, `id` asc.
- `get_surfaced_decision(session, shop_id, action_card_id) -> ActionCard` —
  raises `DecisionNotFound` for a nonexistent id, a card belonging to
  another shop, a card that was never surfaced, or a card whose status has
  since moved past `"active"` (e.g. approved via #717) even if a stale
  `surfaced_at` value remains on the row.
- `DecisionNotFound` — `ValueError` subclass.
- `mask_decision_payload(card: ActionCard) -> dict` — builds the public
  envelope dict for one card: `id` (the card's own uuid — the stable opaque
  per-card identifier; deliberately **not** `workflow_key`), `title`,
  `description`, `severity`, `priority`, `computed_at`, `surfaced_at`
  (freshness / promotion timestamps, #715 + #716), and `recommendation` — an
  **allowlist** copy of `ActionCard.recommendation_payload`'s JSON (never a
  passthrough of the raw dict, which always includes `workflow_key` per
  `persist.py::_build_payload`).

## Masking contract (#718 AC3)

`_mask_recommendation_payload` copies only:
`workflow_name`, `priority`, `rationale`, `preconditions_met`,
`user_action_required`, `source_kpi_ids`, `expected_impact.{metric,value,
confidence}`, `reasoning.{copy_source,why,expected_impact,next_steps,
source_kpi_ids}`. Everything else — `workflow_key` above all, but also any
unexpected key a future bug might introduce (`tool_name`, an internal uuid,
a stray internal field) — is silently dropped by construction. This is an
allowlist, not a blocklist, precisely so a new field added upstream to
`recommendation_payload` does not leak by default; it only reaches the
public response once someone explicitly adds it to the allowlist here.

`title` / `description` are forwarded as-is. They are rules-engine-generated
Decision copy (`WorkflowRecommendation.workflow_name` /
`WorkflowReasoningCopy.why` / `.rationale` at persist time — see
`services/action_cards/persist.py::_build_payload`), not visitor-controlled
input, and are the entire point of a Decisions read surface — matching the
existing authenticated `GET /v1/action-cards` precedent
(`api/routes/action_cards.py::_to_item`, which does the same).

## Dependencies

- `juli_backend.models.models.ActionCard` — read-only; this module issues no
  write, no `session.add`, no `session.commit`.
- Does **not** import `services/action_cards/persist.py` or
  `services/action_cards/emission_budget.py` — only the shared `ActionCard`
  model those two modules also read/write.
- No Redis. Postgres is the sole source of truth (ADR-038) — this module
  only ever reads already-persisted rows; there is no live-scoring code path
  here to fail, so "last-good state on scoring failure" (PRD) is satisfied
  structurally rather than by an explicit fallback branch. A genuine query
  failure propagates as an exception (surfaced as 500 by the API layer,
  `api/routes/demo_decisions.py`) — never silently downgraded to an empty
  list.

## HTTP (via `api/routes/demo_decisions.py`)

- `GET /v1/demo/decisions` — unauthenticated, server-bound
  `DEMO_REFERENCE_SHOP_ID` (same pattern as `GET /v1/demo/analytics`, #531).
  No `X-Shop-Id` header, no bearer token, no client-controllable `shop_id`
  anywhere (query param explicitly rejected with 400, mirroring
  `demo_analytics.py`; no header is ever read; no path segment exists).
  Returns the ranked, emission-gated active Decision envelope list.
- `GET /v1/demo/decisions/{action_card_id}` — same no-auth/server-bound
  contract. 404 (safe default) for a suppressed candidate, a nonexistent id,
  or a card belonging to another shop — all three are indistinguishable in
  the response, so detail lookup never leaks existence across tenants.

## Out of scope

- Any mutation of `ActionCard` (approve/dismiss/execute) — `services/
  demo_execution` (#717, B-5) owns the one existing write path.
- Computing or applying the emission budget itself — `services/
  action_cards/emission_budget.py` (#716, B-4) is upstream of this module.
- Track B Demo UI (#600) — consumer of this HTTP surface, not part of it.
