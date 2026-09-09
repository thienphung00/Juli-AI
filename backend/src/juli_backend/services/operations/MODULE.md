# Module: operations

## Responsibility

Phase 2 operations pipeline backend services. P2-B5 owns workflow outcome
instrumentation after approved tool execution. W8-C (#1655) adds the read-only
post-hoc chain over that instrumentation.

## Public Interface

- `record_workflow_outcome(session, execution, …) -> WorkflowOutcomeRecordResult` —
  persist `workflow_outcome_metrics` envelope after terminal execution (idempotent)
- `load_workflow_outcome_metrics(session, shop_id, approval_id) -> dict` — internal
  validation read model
- `build_workflow_outcome_metrics(…)` — ADR-013 envelope builder
- `list_impact_readings_honest(session, tool_execution_id) -> list[ImpactReading]` —
  ADR-085 d.8 (#1338): the countable readings only
- `COUNTABLE_CONFIDENCES` / `EXCLUDED_CONFIDENCES` — the single declaration of
  the #1226/#1338 exclusion rule; every surface answering "what was the impact"
  reads these instead of re-declaring the tier list
- `load_outcome_chain(session, workflow_run_id, *, now=None) -> OutcomeChain` —
  the five-link post-hoc chain (#1655), in ONE database call
- `LinkReason` (`pending` | `unavailable` | `missing`), `EmptyLink`, `OutcomeChain`
  and the five link payload types

## API

- `GET /v1/workflow-outcomes/{approval_id}` —
  `backend/src/juli_backend/api/routes/workflow_outcomes.py`
- No route exposes `load_outcome_chain`: it is an operator/query surface, and
  rendering is deliberately out of W8 (PRD #1652).

## API

- `GET /v1/workflow-outcomes/{approval_id}` —
  `backend/src/juli_backend/api/routes/workflow_outcomes.py`

## Dependencies

- `models.models.ToolExecution` — terminal execution records (no execution module import)
- `repositories.repos.WorkflowOutcomeRecordsRepo`
- `services.impact.windows.post_window` — the ONLY declaration of ADR-077 d.2's
  window lengths; `outcome_chain` never re-declares T+7
- `services.agent.status` — `NON_TERMINAL_STATUSES` / `WorkflowRunStatus`, the
  vocabulary `outcome_chain` classifies against (it adds no member to it)

## Invariants

- Execution payload must include a validated six-workflow `workflow_id`
- One outcome record per `(shop_id, execution_id)`
- Realtime cadence reflects execution status; other cadences remain preliminary stubs
- A `suppressed` or `confounded` `ImpactReading` is never counted as an impact
  and never collapsed into the other or into zero — one rule
  (`COUNTABLE_CONFIDENCES`/`EXCLUDED_CONFIDENCES`), never a second copy
- `load_outcome_chain` issues exactly ONE statement; reason classification is
  pure Python over that single result set plus an injectable clock
- An empty link always carries a `LinkReason`, never a bare `null`, and the
  vocabulary has exactly three members
- `workflow_runs.action_card_id IS NULL` reads `unavailable` (honest legacy
  data), never `missing`, and is never backfilled

## Out of scope (this module)

- Live OLAP-derived cadence rollups (P2-B8+)
- Dashboard loader swap
- Workflow-specific executors (P2-B6+)
- Rendering or serving the outcome chain (no route, no response model — W8 defers it)

## Owners

- domain: backend
- code: backend/src/juli_backend/services/operations/
