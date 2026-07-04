# Handoff: review → ship — Issue #155

## Guardrails Review

### Critical (must fix before merge)

None.

### Warning

None.

### Info

- `useListingWorkflow.goNext` embeds draft generation inline — acceptable for P1.6 scope; could extract helper in #156 if export step adds complexity.
- Modal overlay uses fixed positioning — verify mobile in manual QA (tests use jsdom).

## Validation checks

| Check | Result |
|-------|--------|
| jest (full suite) | ✓ 207 passed |
| tsc | ✓ (no new linter errors) |
| Security | ✓ No API calls, no external fetch |
| Reliability | ✓ Deterministic filter + rules engine integration |

## PR ready

- Branch: `feature/issue-155-listing-workflow-ui`
- Scope: ~600 lines across state machine, UI, executor extension, tests
- Rollback: revert PR — no migrations, no backend changes

## Test plan

- [x] `npm test -- --testPathPattern=test_listing_workflow_ui`
- [x] Full web suite (207 tests)
- [ ] Manual: approve list_products on seller home in UI-only mode
