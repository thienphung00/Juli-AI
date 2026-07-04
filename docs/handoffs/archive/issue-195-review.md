# Handoff: review → ship — Issue #195

## Issue

- **#195** — Decisions Recommended tab — full ranked cards + approval gate relocation

## PR

- #205 — `feature/issue-195-decisions-recommended-tab` → `main`

## Status

- Critical findings: 0
- Warnings: 0
- Info: In Progress / Workflow Templates sub-tabs are placeholders (#197, #198)

## Modules

| Module | Change |
|--------|--------|
| `DecisionsSubTabs` | Sub-tab chrome: Đề xuất / Đang thực hiện / Mẫu quy trình |
| `OperationsApprovalShell` | Extracted approval host (toolbar, clarity cards, routing) |
| `DecisionsPage` | Wires persona + Recommended shell; placeholders for other tabs |
| `ApprovalGate` | Required inputs + Review link on each card |
| `OperationsPipelineShell` | Delegates to approval shell (legacy test composite) |

## Bootstrap

No parallel agents; single-issue branch.

## Review artifact

- `artifacts/reviews/review-issue-195.json` — PASS, 5/5 AC mapped

## Test Results

- Issue tests: `test_issue195_decisions_recommended.test.tsx` (7)
- Regression: `test_issue193_home_read_only.test.tsx`, `test_operations_approval_gate.test.tsx`
- Full suite: 439 tests passing; type-check + lint clean

## Ready for ship

All acceptance criteria mapped. No migrations. Rollback = revert PR.
