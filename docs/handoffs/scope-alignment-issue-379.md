# Scope alignment — Issue #379 (P2-B6)

**Parent:** #278 · **Slice:** P2-B6 · **Domain:** backend

## In scope

- Register `listing.create_hero_product` and `listing.optimize_product` in `runner.py` (async handlers)
- Route `create_hero_product_1` / `optimize_product_2` via existing `tool_routing.py` (#305)
- Orchestrate Product API chain through `load_sandbox_write_resources` (#301 guard)
- Multipart image/file upload per `contract-collection.md` B-2 / B-2a (URI shape from doc examples)
- Unit + integration tests (noop.ping pattern + mocked API failure → `ToolExecution.failed`)
- Flip `EXECUTION.md` P2-B6 checkbox

## Out of scope

- Action Card auto-approve UI (manual `POST /v1/executions` demonstrates E2E)
- P2-B7 leakage executors (#380)
- Live SANDBOX_VN capture runs in CI (mocked in tests; manual verify optional)

## Resolved decisions

| Decision | Choice |
|----------|--------|
| Multipart upload | Implement in #379; tests mock HTTP; contract URIs as reference |
| Registry location | `runner.py` per explore-agent correction (not `worker.py`) |
| Async handlers | Worker awaits `run_tool_async(session, …)` for sandbox credential load |
