# Module: execution

## Responsibility

Celery-backed dispatch for approved tool calls (P2-B4 / #305). HTTP handlers enqueue
work and return immediately; workers execute tools and persist queryable outcomes.

## Public Interface

- `enqueue_approved_tool(session, shop_id, approval_id, tool_name, payload)` — persist
  queued record + dispatch Celery task
- `get_task_dispatcher()` / `set_task_dispatcher()` — inject dispatcher in tests
- `run_tool(tool_name, payload)` — worker-side registry (not for HTTP handlers)
- `register_tool(name, handler)` — extend tool catalog for later P2-B6+ executors
- `POST /v1/executions` — enqueue approved tool (202)
- `GET /v1/executions/{id}` — query status + outcome
- Celery task `juli_backend.execute_approved_tool`

## Dependencies

- `workers/celery_app` — Celery broker configuration
- `repositories.repos.ToolExecutionsRepo` — Postgres persistence
- `integrations/tiktok/factories` — sandbox write tools (P2-B6+ wiring)

## Invariants

- HTTP route handlers must never call `run_tool` directly
- Write tools must route through sandbox capability guards (#301)
- Execution status is shop-scoped — no cross-tenant reads

## Out of scope (this module)

- Workflow-specific listing/leakage executors (P2-B6+)
- Redis action-card persistence
- Outcome tracking metrics (P2-B5) — see `services/operations/outcome_tracking.py`

## Owners

- domain: backend
- code: backend/src/juli_backend/services/execution/
