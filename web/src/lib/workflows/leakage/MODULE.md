# Leakage Workflow State Machine (P1.7-2)

Client-side step graph and session persistence for the Revenue Leakage executable
workflow. Deterministic — no TikTok API, no Postgres, no ML inference.

## Public surface

| Export | Responsibility |
|--------|----------------|
| `useLeakageWorkflow({ taskId })` | Load fixture, navigate steps, persist session |
| `advanceLeakageStep` / `goBackLeakageStep` | Pure step transitions |
| `canAdvanceLeakage` / `canGoBackLeakage` | Navigation guards |
| `markEvidenceReviewed` | Acknowledge evidence step |
| `checkLeakageEvidencePii` | PII guard for evidence bundles |
| `loadLeakageWorkflowSession` / `saveLeakageWorkflowSession` | `sessionStorage` resume |

## Step graph

`detail` → `evidence` → `root_cause` → `recommended_action` → `execution` → `success`

## Workflow status

`new` → `in_review` → `evidence_reviewed` → `ready_to_execute` → `executing` → `completed` | `skipped`

## Dependencies

- `@/lib/mock-data/leakage-workflow` — `loadLeakageWorkflowTask`, fixture schemas
- `@/lib/mock-data/seller-personas/pii` — masked buyer ID enforcement

## Related UI (P1.7-3)

- `LeakageWorkflowPanel` — modal step renderers; consumes `useLeakageWorkflow` (#166)

## Out of scope (P1.7-2)

- `useTaskExecutor` opens `LeakageWorkflowPanel` on approve for four leakage types; global `TaskDismissModal` on dismiss (#167)
- UX instrumentation events (#168)
