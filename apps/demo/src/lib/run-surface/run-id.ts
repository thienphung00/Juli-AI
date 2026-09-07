/**
 * Distinguishes a real backend run id (a UUID, `workflow_runs.id`) from a
 * legacy mock `ExecutionRecord` id (`exec-<workflowKey>-<n>`, #1320's mock
 * layer) -- both currently resolve through the same dynamic route segment
 * (`/decisions/in-progress/[executionId]`), so the page needs a synchronous,
 * zero-network way to route between the two renderers. A UUID shape is
 * exactly that: no fetch required, no ambiguity with the mock id format.
 */
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function looksLikeRunId(id: string): boolean {
  return UUID_PATTERN.test(id);
}
