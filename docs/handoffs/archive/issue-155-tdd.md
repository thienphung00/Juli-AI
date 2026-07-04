# Handoff: tdd → review — Issue #155

## Issue

- **#155** — E2E listing workflow UI — dual-path state machine from approved list_products
- **Branch:** `feature/issue-155-listing-workflow-ui`

## What shipped

### New files

| File | Purpose |
|------|---------|
| `web/src/lib/workflows/new-seller/listing/state-machine.ts` | Path A/B step reducer with back navigation |
| `web/src/lib/workflows/new-seller/listing/filter-opportunities.ts` | Deterministic opportunity filter |
| `web/src/lib/workflows/new-seller/listing/use-listing-workflow.ts` | Workflow session hook + draft generation |
| `web/src/components/workflows/new-seller/listing/ListingWorkflowPanel.tsx` | Modal UI with Vietnamese labels |
| `web/src/components/workflows/new-seller/listing/index.ts` | Barrel export |
| `web/src/__tests__/test_listing_workflow_ui.test.tsx` | 7 integration tests |

### Modified files

| File | Change |
|------|--------|
| `web/src/lib/task-executor/use-task-executor.ts` | `list_products` opens workflow + launch feedback |
| `web/src/components/tasks/TaskQueue.tsx` | Renders `ListingWorkflowPanel` when open |
| `web/src/lib/workflows/new-seller/listing/index.ts` | Re-exports state machine + filter + hook |
| `docs/architecture/map.md` | Deployed UI module row |

## Tests written

| Test | Behavior |
|------|----------|
| `opens listing workflow when list_products is approved` | Entry point + launch feedback |
| `keeps Phase 1 no-op feedback for non-list_products tasks` | Other types unchanged |
| `reaches draft review with generated draft from rules engine` | Path A E2E → `ready_for_export` |
| `preserves session data when navigating back` | Back nav keeps form values |
| `returns deterministic card set for fixed constraints` | Path B filter unit assertion |
| `shows filtered opportunities in the browse step` | Path B UI cards |
| `does not call backend APIs during workflow` | UI-only mode |

## Acceptance criteria status

| Criterion | Status | Covered by |
|-----------|--------|------------|
| Approve list_products opens workflow | ✓ | entry test |
| Path A → draft review | ✓ | Path A E2E test |
| Path B → constraints → browse → draft | ✓ | filter + browse tests (draft via rules at review step) |
| Back navigation preserves data | ✓ | back nav test |
| Other tasks no-op | ✓ | shop_setup test |
| Integration test entry marker | ✓ | `listing-workflow` testid |
| Path A draft from rules engine | ✓ | draft review assertions |
| Path B deterministic filter | ✓ | filter test |
| UI-only no backend | ✓ | API mock test |
| map.md updated | ✓ | map.md row |

## Notes for review

- Export step is placeholder only (#156)
- Draft generated on transition to `draft_review` via `generateProductDraft` (#154)
- Path B filter test constraints documented in test constants
