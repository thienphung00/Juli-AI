## Handoff: tdd → review

### Issue
- #195 — Decisions Recommended tab — full ranked cards + approval gate relocation

### Branch
- `feature/issue-195-decisions-recommended-tab`

### Changes Summary
- New: `DecisionsSubTabs`, `OperationsApprovalShell`, `test_issue195_decisions_recommended.test.tsx`
- Modified: `DecisionsPage`, `ApprovalGate` (required inputs + review link), `OperationsPipelineShell` (delegates to approval shell), MODULE docs, `#191` test

### Tests Written
- `test_issue195_decisions_recommended.test.tsx` — sub-tabs, full list, approval toolbar on Decisions, Home regression, NPL approve + noop paths

### Test Results
- All 439 tests passing
- Lint: clean (pre-existing CreatorsPage img warning only)
- Type-check: clean

### Acceptance Criteria Status
- [x] `/decisions` opens on Recommended sub-tab with full ranked list
- [x] Approve-all, selective approve, reject-with-reason (via shared `OperationsApprovalShell` / `#181` tests)
- [x] Home has no approval controls (`#193` + `#195` regression tests)
- [x] NPL → listing modal; deferred → no-op toast
- [x] Integration test: Decisions tab approve path for NPL

### Notes for Reviewer
- In Progress / Workflow Templates sub-tabs are placeholders (#197, #198)
- Review links target `/decisions/[workflow_id]` ahead of detail flow (#196)

## Guardrails Review

### Critical
- None

### Warning
- None

### Info
- `OperationsPipelineShell` retained for existing `#181`/`#182` tests; production approval path is `DecisionsPage` → `OperationsApprovalShell`
