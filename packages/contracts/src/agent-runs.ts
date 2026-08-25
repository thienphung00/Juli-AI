/**
 * TypeScript mirror of the agent runs list response shape — GET /v1/demo/runs
 * (issue #1310, ADR-083 T4).
 *
 * Mirrors `backend/src/juli_backend/api/routes/agent_runs.py` field-for-field:
 * `WorkflowRunListItem`, `PendingDecisionSummary`, and `WorkflowRunListResponse`.
 * Both sides are proven via a cross-language golden test
 * (`tests/unit/test_agent_runs_list_contract.py`).
 */

/**
 * Summary of a pending decision request on a waiting_approval run.
 */
export interface PendingDecisionSummary {
  tool_call_id: string;
  expires_at: string;
}

/**
 * One run in the seller's polled read model of their workflow runs.
 */
export interface WorkflowRunListItem {
  id: string;
  status: string;
  stop_reason: string | null;
  product_name: string;
  created_at: string;
  completed_at: string | null;
  running_seconds_elapsed: number;
  latest_narration: string | null;
  decision_summary: PendingDecisionSummary | null;
}

/**
 * Polled read model response for GET /v1/demo/runs — the seller's list of
 * their workflow runs, each with status, product binding, timestamps, latest
 * narration line, and for waiting_approval runs, the pending decision summary.
 */
export interface WorkflowRunListResponse {
  success: boolean;
  data: WorkflowRunListItem[];
}
