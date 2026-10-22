# backend/src/juli_backend/services/run_changes

## Purpose

Before/after values of Juli's agent writes (`run_write_values`, migration 078),
"Hoàn tác" revert runs, seller rules and the day-7 "Hoàn tác?" guardrail (fast
track P8-C, ADR-109 d.9-12, S-FR-8). P60-1b (ADR-107 "Amendment 2026-10-20" §6,
§9; migration 096) adds content hashes, the before-read time and the audit link
to every write row, and runs the revert check on hashes.

## Public API

- `SqlWriteValueRecorder(session, shop_id=..., workflow_run_id=...).record(...)` --
  one row per changed field, with `before_hash` / `after_hash`
  (`product_history.normalize.field_value_hash`), `before_read_at` (the
  executor's before read, `FieldWrite.before_read_at`) and
  `production_write_audit_id` when exactly one `production_write_audit` row
  matches (`run_id`, `tiktok_product_id`, `mutation_kind` = tool name), else
  NULL. Never raises.
- `start_revert(...)`, `load_run_changes(...)` (each `FieldChange` carries the
  latest `after_hash`), `RevertPlan` (`expected_hashes` travel in the run state
  only when present), `RevertPlanner`, `REVERT_LISTING_PLAYBOOK`.
- Guardrail / questions / rules: unchanged.

## Invariants

- The three-way revert check (live = Juli's after -> restore; else refuse,
  `external_change`) compares hashes when both sides have one and values
  otherwise (`write_capture.changed_fields(expected_hashes=...)`); the outcome
  is the same either way. Prices are never reverted (fast-track D13); a Seller
  Center promotion run is refused (`seller_center`).
- `run_write_values` is append-only for `juli_app` (SELECT, INSERT).
- `read_live_product(session, shop_id, tiktok_product_id, write_mode)` (P61-F) reads the
  listing through the mode the reverted run wrote with: `live` -> the shop's own production
  read credential (`composition.build_read_resources`), anything else (`simulated`, NULL) ->
  the sandbox write resources. `start_revert` passes the reverted run's `write_mode`; the
  revert run's own write goes live only if the reverted run was live
  (`composition.resolve_agent_write_leg(is_revert=True, ...)`), otherwise it stays on the
  sandbox, and a revert of a live run fails by name rather than restoring on the sandbox.
- A live agent write (P61-F) records an allowed `production_write_audit` row (mutation kind
  = the tool name), so its `run_write_values` link to it (the recorder prefers the single
  allowed row over a refusal row of the same mutation); a sandbox write has none, so its
  link stays NULL.

## Dependencies

`models.run_changes`, `models.models` (`ProductionWriteAudit`, `WorkflowRun`,
`Product`), `services.agent.runner.write_capture`, `services.product_history.normalize`.
