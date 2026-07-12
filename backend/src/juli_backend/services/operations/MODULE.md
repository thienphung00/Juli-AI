# Module: operations

## Responsibility

Phase 2 operations pipeline backend services. P2-B5 owns workflow outcome
instrumentation after approved tool execution.

## Public Interface

- `record_workflow_outcome(session, execution, …) -> WorkflowOutcomeRecordResult` —
  persist `workflow_outcome_metrics` envelope after terminal execution (idempotent)
- `load_workflow_outcome_metrics(session, shop_id, approval_id) -> dict` — internal
  validation read model
- `build_workflow_outcome_metrics(…)` — ADR-013 envelope builder

## API

- `GET /v1/workflow-outcomes/{approval_id}` —
  `backend/src/juli_backend/api/routes/workflow_outcomes.py`

## Dependencies

- `services/execution` — terminal execution records (`tool_executions`)
- `repositories.repos.WorkflowOutcomeRecordsRepo`

## Invariants

- Execution payload must include a validated six-workflow `workflow_id`
- One outcome record per `(shop_id, execution_id)`
- Realtime cadence reflects execution status; other cadences remain preliminary stubs

## Out of scope (this module)

- Live OLAP-derived cadence rollups (P2-B8+)
- Dashboard loader swap
- Workflow-specific executors (P2-B6+)

## Owners

- domain: backend
- code: backend/src/juli_backend/services/operations/
