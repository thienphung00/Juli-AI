# Decision view-model (P1.8-9)

Seller-facing **Decision** envelopes mapped from ADR-026 `workflow_recommendations`.
Pure functions only — no HTTP, no React. UI layers (#193, #195, #199) consume
this module; execution remains keyed by `workflow_id`.

## Public surface

| Export | Responsibility |
|--------|----------------|
| `toDecision(recommendation)` | Map one `WorkflowRecommendation` → `Decision` |
| `toDecisionsFromRecommendations(recommendations)` | Batch map; filters unknown `workflow_id` |
| `sortDecisionsByImpact(decisions)` | Descending sort by `estimated_impact.value` |
| `takeTopDecisions(decisions, n)` | Top *n* after impact sort (Home preview uses `n=3`) |
| `resolveDecisionStatus(options)` | Derive `DecisionStatus` from approval + executor mock state |
| `applyDecisionLifecycle(decision, options)` | Merge lifecycle into a `Decision` copy |
| `isValidatedWorkflowId(id)` | ADR-026 catalog guard (six workflows only) |
| `getRequiredInputsForWorkflow(workflowId)` | Static required-input catalog per workflow (mock P1.8-9) |

## Decision envelope

| Field | Source |
|-------|--------|
| `id` | `workflow_id` (one decision per validated workflow per session) |
| `workflow_id` | `WorkflowRecommendation.workflow_id` |
| `title` | `workflow_name` |
| `estimated_impact` | `expected_impact.metric` + `value` |
| `confidence` | `expected_impact.confidence` |
| `reasoning_summary` | `rationale` (rules-only; full copy via `buildWorkflowReasoning`) |
| `required_inputs` | Per-workflow mock catalog |
| `status` | `recommended` default; lifecycle helpers set `needs_input` / `executing` / `completed` |

## Lifecycle (mock P1.8-9)

`applyDecisionLifecycle` merges disposition from `OperationsApprovalSession`
(`useOperationsApproval`) and optional executor phase:

| Disposition | Executor | Inputs | Status |
|-------------|----------|--------|--------|
| `pending` / `rejected` | — | — | `recommended` |
| `approved` | — | missing | `needs_input` (when `userActionRequired`) |
| `approved` | `executing` | collected | `executing` |
| `approved` | `completed` | — | `completed` |

P2 swaps session/executor sources; status enum and mapping stay stable.

## Dependencies

- `@/lib/operations/recommendations` — `WorkflowRecommendation`, `ImpactConfidence`
- `@/lib/operations/approval-session` — `WorkflowApprovalDisposition`
- `@/lib/mock-data/operations/schemas` — `ValidatedWorkflowId`, `VALIDATED_WORKFLOW_IDS`

## Consumers (planned)

- `HomeSummaryShell` — `takeTopDecisions(_, 3)` (#193)
- `DecisionsPage` Recommended / In Progress (#195, #197)
- Juli Chat decision context (#199)
