import type { WorkflowRunListItem } from "@juli/contracts";

/**
 * Builds a `WorkflowRunListItem` satisfying the real polled read-model
 * contract shape (`GET /v1/demo/runs`, `packages/contracts/src/agent-runs.ts`)
 * -- every test in this slice constructs runs against this exact interface
 * rather than a hand-authored ad hoc shape.
 */
export function buildRunListItem(
  overrides: Partial<WorkflowRunListItem> & Pick<WorkflowRunListItem, "id">,
): WorkflowRunListItem {
  return {
    status: "running",
    stop_reason: null,
    product_name: "Áo thun cotton nam",
    created_at: "2026-08-25T09:00:00.000Z",
    completed_at: null,
    running_seconds_elapsed: 12,
    latest_narration: null,
    decision_summary: null,
    ...overrides,
  };
}
