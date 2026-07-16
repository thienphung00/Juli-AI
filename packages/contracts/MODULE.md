# Module: contracts

## Responsibility

Shared typed contracts for execution lifecycle, review stages, and workflow input
descriptors introduced in Phase 2.6. Demo apps import these shapes; fixture prose
remains in app-level libs until a later migration.

## Public interface

- `ExecutionTimelineStepStatus` — pending, running, succeeded, failed.
- `ExecutionLifecycleStatus` — needs_input, executing, completed.
- `ExecutionTimelineStep` — numbered action/wait/outcome step with optional recovery.
- `ExecutionRecord` — one approved workflow execution with timeline and input snapshot.
- `ReviewStage` / `ReviewStageContent` — five-stage recommendation review copy.
- `ReviewInputFieldDescriptor` — editable Inputs-stage field metadata.
- `deriveLifecycleFromTimeline(timeline)` — maps step states to lifecycle status.

## Dependencies

- None (pure TypeScript types and helpers).

## Invariants

- Helpers are pure and perform no network or environment access.
- Lifecycle values match `demo-state` and In Progress design docs exactly.
- This package never imports an app.

## Owners

- domain: web
- code: `packages/contracts/`
