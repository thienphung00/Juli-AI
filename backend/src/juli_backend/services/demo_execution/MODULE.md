# backend/src/juli_backend/services/demo_execution

## Purpose

Public Mock Demo **approve → execute** dry-run path for a Decision
(`ActionCard`) — #717, B-5, ADR-037 (Demo no-auth) / ADR-038 §9 (dry-run,
settled: "UX may simulate success/progress against local/demo execution
records only"). This module is the *entire* durability boundary for that
flow: it never calls a real Partner (TikTok) write client, never enqueues
Celery work, and never requires reference-merchant credentials.

This slice delivers **backend record/state only, not UI** — Track B UI (#600,
execution progress card #696/#697) reads the persisted narrative. The public
Demo Decisions **read** API (listing/detail) is #718 (B-6), out of scope here.

## Why an isolated module, not a `dry_run` flag on the real path

The PRD is explicit and non-negotiable: build an isolated dry-run module
rather than adding a `dry_run` flag to `services/execution` (the real
Partner-write dispatch path — `enqueue_approved_tool` / `run_tool_async`). A
flag is one bad conditional away from a real Partner write against
reference-merchant credentials. This module's source files therefore must
never import `juli_backend.integrations.tiktok` (home of `TikTokClient` /
`SandboxWriteClientFactory`) or `juli_backend.services.execution` (home of
the two forbidden functions) — statically enforced, not just
runtime-asserted, by
`tests/unit/test_demo_execution_import_boundary.py` (AC3): it walks the
transitive `juli_backend.*` import graph starting at this module's own
`.py` files (following only edges through other `services.*` modules) and
fails if that graph ever reaches `integrations.tiktok`, `services.execution`,
`repositories` (`repositories/repos.py` itself imports
`integrations.tiktok`), or `api`. A written import can be seen and forbidden
by this check under every possible runtime branch; a runtime mock-call-count
assertion (also present, `test_approve_never_invokes_the_partner_write_module`
in `tests/unit/test_demo_execution_dry_run.py`) can only prove the branches it
happens to exercise. AC3 is the structural guarantee behind AC1.

## Why a new table (`demo_execution_records`), not reused `tool_executions`

`015_tool_execution_fields.py` / `services/execution` already model
executions via `ToolExecution` (`tool_executions` table), but that table's
whole meaning is "Celery-dispatched, and eventually a real TikTok write
happened" — `enqueue_approved_tool` creates the row and hands it to a Celery
task; `GET /v1/executions/{id}` reports real `outcome`/`error`/`error_category`
from a real API call. Reusing it for demo dry-runs would either (a) require
adding a `is_dry_run`/`dry_run` column and branching real-execution code
paths on it — exactly the flag risk this slice was told to avoid — or (b)
silently mix rows a Celery worker will never pick up into a table a real
reconciliation job scans expecting genuine outcomes. A brand-new table
(migration `028_demo_execution_records`) with its own three-state progress
machine (`queued`/`running`/`done` — deliberately distinct from
`ExecutionStatus`'s `queued`/`running`/`succeeded`/`failed`, since a demo
dry-run has no failure mode to model) keeps the two entirely separate. The
migration is additive-only (new table, two new indexes; no existing table
touched) and satisfies `tests/unit/test_migration_additive_gate.py`.

## Routing note (Meta-authorized)

Migrations normally belong to the `data-platform` domain. Meta explicitly
authorized the `backend` executor to write this migration and own the call
site for this slice, because splitting it across domains had twice produced
correct code nothing called in this wave (the call site lives in backend
paths — `api/routes/demo_execution.py`).

## Public Interface

- `approve_decision_dry_run(session, *, shop_id, action_card_id, now=None)`
  → `DemoExecutionRecord` — marks the target `ActionCard` `status="approved"`
  / `approved_at` (first writer of that seller-lifecycle transition;
  `services.action_cards.persist.IN_FLIGHT_STATUSES` already expects
  `"approved"` and will not overwrite it on rescoring), then creates and
  synchronously advances a `DemoExecutionRecord` through
  `queued → running → done`, appending a `{state, message, at}` step to
  `narrative_json` at each transition. Raises `DecisionNotFound` if no
  `ActionCard` with that id exists for `shop_id` (tenant-scoped; never leaks
  another shop's row).
- `DemoExecutionState` — `StrEnum`: `QUEUED` / `RUNNING` / `DONE`.
- `DecisionNotFound` — `ValueError` subclass.
- `narrative_steps(record)` → `list[dict]` — decode `narrative_json`.

## HTTP (via `api/routes/demo_execution.py`)

- `POST /v1/demo/decisions/{action_card_id}/approve` — unauthenticated,
  server-bound `DEMO_REFERENCE_SHOP_ID` (same pattern as
  `GET /v1/demo/analytics`, #531, via `api/routes/demo_analytics.py`'s
  `get_demo_reference_shop_id`). No `X-Shop-Id` header, no bearer token. 200
  with `{execution_id, action_card_id, status, narrative}` on success; 404 if
  the Decision does not exist for the reference shop. Response body
  deliberately omits `workflow_key` — internal identifiers stay out of the
  public Demo response body (same standard #718/B-6 sets for the read API).

## Key behaviors

- **No Celery, no TikTok, ever** — the whole `queued → running → done`
  progression runs synchronously, in-process, inside one call to
  `approve_decision_dry_run`. There is no background worker to accidentally
  wire to a real dispatcher later.
- **No Partner auth required (AC4)** — nothing in this module reads
  `TikTokCredential`; a shop with zero credential rows approves successfully.
- Sole write owner for `demo_execution_records` — no other module writes it
  (registered in `docs/architecture/ownership-registry.yml`, owner
  Intelligence, alongside `action_cards`).
- Deterministic testing: `approve_decision_dry_run(..., now=<callable>)`
  injects the clock — every narrative step's timestamp comes from the same
  injected clock rather than three separate `datetime.now()` calls.

## Out of scope

- Public Demo Decisions read API (listing/detail) — #718, B-6.
- Dismiss / re-run / cancel dry-run actions — not named in #717's acceptance
  criteria.
- Any wiring back into `services.action_cards.persist` /
  `emission_budget` — this module reads `ActionCard` directly via the ORM
  session (same pattern as `services/action_cards/emission_budget.py`) and
  does not call either of those modules' functions.
