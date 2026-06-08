# Module: leakage-workflow (mock data)

## Responsibility

Phase 1.7 mock fixtures for Revenue Leakage executable workflow entities:
`LeakageWorkflowTask` with evidence bundles, root cause, recommended action,
execution plan, and success payload. Typed schemas aligned with
`docs/data-models/canonical-entities.md` § Leakage workflow entities.

## Public Interface

- `loadLeakageFixtures()` — all four leakage workflow tasks (stable IDs)
- `loadLeakageWorkflowTask(taskId)` — single task by ID (`task_leak_001`…`004`)
- `validateLeakageFixtures()` — schema validation for all fixture sets
- `LEAKAGE_TASK_TYPES` — `return_spike` | `buyer_cancellation_cluster` | `refund_cluster` | `return_window_policy`

## Dependencies

- `@/lib/mock-data/seller-personas/schemas` — `MockOrder`, `MockReturn`, `MockTask` base types
- `@/lib/mock-data/seller-personas/pii` — masked buyer ID validation

## Invariants

- Stable task IDs aligned with `leakage-persona.ts` task cards
- All four task types present exactly once
- Evidence bundles use masked `buyer_id` (`buyer_***`) only — Forbidden #17
- No TikTok API calls; no Postgres writes
- `affiliate_fraud` is not a valid task type (ADR-025)

## Owners

- domain: web
- code: `web/src/lib/mock-data/leakage-workflow/`
- EXECUTION slice: P1.7-1 (issue #164)
