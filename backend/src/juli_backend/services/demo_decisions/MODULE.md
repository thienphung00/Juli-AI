# backend/src/juli_backend/services/demo_decisions

## Purpose

Demo Decisions **read** service (originally #718, B-6; auth posture updated
by #1283, AGT-W5A) — the query + masking layer behind
`GET /v1/demo/decisions` (list) and `GET /v1/demo/decisions/{id}` (detail).
This is the read counterpart to `services/demo_execution` (#717, B-5, the
approve → dry-run write path, itself since retired by #1222 — see that
module's own MODULE.md) and consumes, but never mutates, persistence owned
by #715 (B-3, `services/action_cards/persist.py`) and #716 (B-4,
`services/action_cards/emission_budget.py`).

**This module's own functions never changed for #1283.**
`list_surfaced_decisions(session, shop_id)` /
`get_surfaced_decision(session, shop_id, action_card_id)` already took an
arbitrary `shop_id` — the #1283 fix was entirely at the HTTP layer
(`api/routes/demo_decisions.py`): resolving that `shop_id` from the
authenticated caller's `X-Shop-Id` via `get_active_shop` instead of a
server-bound `DEMO_REFERENCE_SHOP_ID`. See that route module's own docstring
for the full rationale — on the deployed host the reference shop was a real
merchant's production shop, so the unauthenticated routes served a live
seller's recommendations to any caller with no credentials at all.

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

- `GET /v1/demo/decisions` — authenticated (`get_current_user` +
  `get_active_shop`, ADR-075 decision 3, #1283). 401 without a valid JWT;
  shop scope resolves from the authenticated caller's `X-Shop-Id` header,
  ownership-checked by `get_active_shop` — the same channel every other
  authenticated `/v1/*` read route uses. No `shop_id` query param (removed
  by #1283 — that guard existed only to stop a caller redirecting the old
  unauthenticated, server-bound route off the reference shop; its rationale
  is gone once shop scope is a real per-caller value). Returns the ranked,
  emission-gated active Decision envelope list for the caller's own shop —
  a shop with zero cards gets an empty list, never another shop's cards.
- `GET /v1/demo/decisions/{action_card_id}` — same authenticated contract.
  404 (safe default) for a suppressed candidate, a nonexistent id, or a card
  belonging to another shop — all three are indistinguishable in the
  response, so detail lookup never leaks existence across tenants, never
  403 (no existence oracle).
- A card returned by the list route is approvable by the same caller via
  `POST /v1/demo/decisions/{id}/approve` (`api/routes/demo_execution.py`) —
  both routes resolve shop scope through the identical `get_active_shop`
  channel, closing the listing/approving split #1283 found (a caller could
  previously see a card here that a different, server-bound shop scope made
  it approve against, 404ing as cross-tenant).

## Row-level resilience (#718 Review finding 1)

`mask_decision_payload` is a plain allowlist *copy* — it does not type-check
values, so a persisted `recommendation_payload` with the wrong shape for a
known-safe key (e.g. `source_kpi_ids` holding a list of dicts instead of
`list[str]`) passes straight through it unchanged. The strict pydantic
response schema in `api/routes/demo_decisions.py`
(`DemoDecisionItem`/`DemoDecisionRecommendation`) is what actually rejects
that shape — the correct security outcome, since it means a malformed row
can never be serialized into the public response body regardless of cause.

What the schema rejecting a row must **not** do is take the rest of a
public, unauthenticated feed down with it:

- **List** (`GET /v1/demo/decisions`) is per-row resilient:
  `api/routes/demo_decisions.py::_build_masked_item` wraps
  `DemoDecisionItem(**mask_decision_payload(card))` in its own
  `try`/`except ValidationError` and returns `None` for a row that fails,
  which `list_demo_decisions` filters out. A malformed row is dropped —
  never serialized, never leaked, never distinguishable in the response from
  a row that was simply never surfaced — while every other well-formed row
  in the same response is still served. This module's own read functions
  (`list_surfaced_decisions` / `get_surfaced_decision`) are untouched by
  this — they still return whatever `ActionCard` rows the query matches; the
  drop happens one layer up, at construction of the public envelope.
- The drop is observable: one `demo_decisions_row_dropped_invalid_shape`
  warning log per dropped row, carrying only `reference_shop_id` (the
  server-bound demo shop id, never visitor-controlled), the card's own
  opaque `id`, and a structural pydantic validation reason (field path +
  error type/message via `ValidationError.errors(include_input=False, ...)`)
  — never the raw `recommendation_payload`, never `title`/`description`,
  and never `workflow_key`, matching the no-PII/no-raw-content discipline
  `services/action_cards/emission_budget.py`'s suppression logging follows.
- **Detail** (`GET /v1/demo/decisions/{id}`) is deliberately **not**
  row-resilient the same way. A single lookup has no partial result to
  preserve — there is nothing to "serve the rest of". Silently downgrading
  a malformed row to a 404 would misrepresent a genuine data-integrity
  problem as "this Decision doesn't exist" (a strictly worse signal for
  on-call debugging, and a caller reaching this endpoint by id almost always
  got that id from a prior list response, so a vanished-looking 404 would be
  actively misleading). A malformed row at detail therefore surfaces through
  the same `except Exception` -> 500 contract as any other unexpected read
  failure on this route, logged via the existing
  `demo_decisions_detail_failed` entry (now also carrying `action_card_id`).

## Out of scope

- Any mutation of `ActionCard` (approve/dismiss/execute) — `services/
  demo_execution` (#717, B-5) owns the one existing write path.
- Computing or applying the emission budget itself — `services/
  action_cards/emission_budget.py` (#716, B-4) is upstream of this module.
- Track B Demo UI (#600) — consumer of this HTTP surface, not part of it.
