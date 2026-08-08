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

## Idempotency contract (Review hardening, #717 B-5)

`POST /v1/demo/decisions/{action_card_id}/approve` is a public,
**unauthenticated** write with no rate limiting anywhere in this diff.
Without a guard, every repeat approve for the same card (double-click,
client retry, replay) would create a new `DemoExecutionRecord` row —
unbounded row growth driven entirely by anonymous traffic.

`approve_decision_dry_run` is therefore idempotent per `(shop_id,
action_card_id)`: after the tenancy check (`DecisionNotFound` still raised
first for a card belonging to another shop, or a card that does not exist —
idempotency never masks that), it looks up an existing
`DemoExecutionRecord` for that pair using the existing
`ix_demo_execution_records_action_card` `(shop_id, action_card_id)` index.
If one exists, it is returned as-is — already `done`, from the first call's
synchronous `queued → running → done` run — with no re-run of the state
machine and no second write to `ActionCard.status`/`approved_at`. Only the
first approve for a given card runs the narrative; every repeat is a
read-only no-op from the caller's point of view.

**Enforced in application logic only, not a DB uniqueness constraint.** A
`UNIQUE (shop_id, action_card_id)` constraint would be the stronger,
concurrency-safe guarantee, but adding one now is not provably a *safely
additive* migration: this table (migration `028_demo_execution_records`) has
already shipped ahead of this hardening pass, on a public, unauthenticated
endpoint, with the exact duplicate-row bug this fix closes — so a deployed
environment may already contain duplicate `(shop_id, action_card_id)` rows,
and a `CREATE UNIQUE INDEX` / `ALTER TABLE ... ADD CONSTRAINT` against
existing duplicates fails outright rather than applying. Application-level
idempotency (the read-then-return-existing check above) has no such
precondition and degrades gracefully in every environment, deployed or not.
This means the guard is not race-safe under truly concurrent duplicate
requests for the same card arriving before either has committed (a
uniqueness constraint would be); given this is a Demo surface behind a
severity Review rated medium (not a ship-blocker), that trade-off is
accepted rather than blocking on a schema change whose safety cannot be
verified against unknown deployed data. A future slice that adds a
migration to de-duplicate any existing rows first could safely add the
constraint afterward.

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
