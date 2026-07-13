# Module: execution

## Responsibility

Celery-backed dispatch for approved tool calls (P2-B4 / #305). HTTP handlers enqueue
work and return immediately; workers execute tools and persist queryable outcomes.

Reopened #305 adds dispatch infrastructure for P2-B6/B7 real executors: workflow routing,
sandbox write guard contract, idempotency key threading, and error taxonomy.

## Public Interface

- `enqueue_approved_tool(session, shop_id, approval_id, tool_name, payload, idempotency_key=None)` —
  persist queued record + dispatch Celery task
- `resolve_tool_name(workflow_key)` / `resolve_tool_name_for_workflow(workflow_key)` —
  map Action Card `workflow_key` → registered Celery `tool_name` (mirrors
  `services/tiktok/webhook_catalog.py` lookup shape)
- `get_task_dispatcher()` / `set_task_dispatcher()` — inject dispatcher in tests
- `run_tool(tool_name, payload)` — worker-side registry in `runner.py` (not for HTTP handlers)
- `register_tool(name, handler)` — extend tool catalog for P2-B6+ executors
- `load_sandbox_write_resources(session, app_key, app_secret)` — SANDBOX_VN write path for real tools
- `build_sandbox_write_resources(config)` — lower-level guard entry when config is already resolved
- `is_noop_tool(tool_name)` — smoke-test tools that skip TikTok write guards
- `POST /v1/executions` — enqueue approved tool (202); optional `idempotency_key`
- `GET /v1/executions/{id}` — query status, outcome, `error`, `error_category`
- Celery task `juli_backend.execute_approved_tool`

## Workflow → tool routing

Authoritative map: `services/execution/tool_routing.py` (`WORKFLOW_TOOL_CATALOG`).
Keys align with `WORKFLOW_COPY_TEMPLATE_KEYS` in `services/scoring/copy_layer.py`.

| workflow_key | tool_name (P2-B6/B7 registers handler) |
|---|---|
| `create_hero_product_1` | `listing.create_hero_product` |
| `optimize_product_2` | `listing.optimize_product` |
| `replenish_inventory_3` | `inventory.replenish` |
| `clear_excess_4` | `inventory.clear_excess` |
| `process_order_5` | `fulfillment.process_order` |
| `create_activity_7a` | `promotion.create_activity` |
| `update_activity_7c` | `promotion.update_activity` |
| `delete_activity_7b` | `promotion.delete_activity` |
| `prevent_cancellation_8a` | `returns.prevent_cancellation` |
| `prevent_return_8b` | `returns.prevent_return` |
| `prevent_refund_8c` | `returns.prevent_refund` |

`noop.ping` remains registered for smoke tests and is not routed from a workflow key.

## Sandbox write guard contract (P2-B6 / P2-B7)

Real (non-noop) tool handlers **must** call TikTok write endpoints only through guarded
sandbox resources from #301 — never instantiate `TikTokClient` directly.

```python
from juli_backend.services.execution.sandbox_guard import (
    is_noop_tool,
    load_sandbox_write_resources,
)

async def my_write_tool(payload: dict) -> dict:
    if is_noop_tool("listing.create_hero_product"):
        ...
    resources = await load_sandbox_write_resources(
        session,
        app_key=settings.tiktok_app_key,
        app_secret=settings.tiktok_app_secret,
    )
    # e.g. resources.products.create_product(...)
    idempotency_key = payload.get("idempotency_key")  # threaded by worker when set
```

`load_sandbox_write_resources` resolves `SANDBOX_VN` credentials via
`resolve_sandbox_write_credential` and builds resources through `SandboxWriteClientFactory`
(`integrations/tiktok/factories.py`), which applies `SandboxOnlyWriteGuard` before signing.

## Idempotency

When `POST /v1/executions` includes `idempotency_key`, it is persisted on `ToolExecution`
and merged into the Celery worker payload as `payload["idempotency_key"]` before
`run_tool`. P2-B7 approve/reject handlers pass this through to TikTok write endpoints
that support `idempotency_key`.

## Error taxonomy

`ToolExecution.error_category` (coarse enum on `ExecutionErrorCategory`):

| category | meaning | examples |
|---|---|---|
| `validation` | terminal — bad input or guard rejection | `ValueError`, `TransportGuardError` |
| `tiktok_api` | terminal TikTok business error | most `TikTokAPIError` |
| `transient` | retryable | `RateLimitError`, `TikTokSystemError` |
| `unknown` | unclassified | other exceptions |

`error_message` remains human-readable detail for Outcome Tracking (#306).

## Dependencies

- `workers/celery_app` — Celery broker configuration
- `repositories.repos.ToolExecutionsRepo` — Postgres persistence
- `integrations/tiktok/factories` — sandbox/production capability-separated clients (#301)
- `core/security/credential_resolver` — `resolve_sandbox_write_credential`

## Invariants

- HTTP route handlers must never call `run_tool` directly
- Write tools must route through sandbox capability guards (#301) — see contract above
- Execution status is shop-scoped — no cross-tenant reads
- Registry (`register_tool` / `run_tool`) lives in `runner.py`; `worker.py` orchestrates DB + outcome

## Listing executors (P2-B6 / #379)

Registered async tools in `listing_handlers.py`:

- `listing.create_hero_product` — Create Hero Product chain via sandbox write resources
- `listing.optimize_product` — Optimize Product chain (get → edit → update price)

Handlers load credentials through `load_sandbox_write_resources` and orchestrate calls in
`listing.py`. Multipart image/file upload uses `ProductsResource.upload_product_image` /
`upload_product_file` (contract-collection.md §B-2 / B-2a URI shapes).

## Out of scope (this module)

- Leakage workflow executors (P2-B7)
- Redis action-card persistence
- Outcome tracking metrics (P2-B5) — see `services/operations/outcome_tracking.py`

## Owners

- domain: backend
- code: backend/src/juli_backend/services/execution/
