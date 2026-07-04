# Handoff: review → ship — Issue #198

## Issue

- **#198** — Workflow Templates sub-tab — advanced per-workflow settings (mock)

## PR

- #208 — `feature/issue-198-workflow-templates` → `main`

## Status

- Critical findings: 0
- Warnings: 0
- Info: Session-local mock state only; no backend persistence in P1.8-9

## Modules

| Module | Change |
|--------|--------|
| `DecisionsWorkflowTemplatesShell` | Advanced sub-tab host + helper notice |
| `WorkflowTemplateGroup` | Per-workflow slider/toggle controls |
| `workflow-templates` | Mock definitions + sessionStorage helpers |
| `DecisionsPage` | Wires Templates shell (replaces placeholder) |

## Bootstrap

Single-issue branch from `origin/main` in `.worktrees/issue-198`.

## Review artifact

- `artifacts/reviews/review-issue-198.json` — PASS, 4/4 AC mapped

## Test Results

- Issue tests: `test_issue198_decisions_templates.test.tsx` (5)
- Regression: `test_issue191_decisions_shell`, `test_issue195_decisions_recommended`
- Type-check + lint clean

## Ready for ship

All acceptance criteria mapped. No migrations. Rollback = revert PR.
