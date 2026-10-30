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
 * Fast track P67 (D75 Q2): what a sandbox reviewer's run wrote on TikTok, and when TikTok
 * confirmed it (the ledger row `succeeded`; a refused write never counts).
 */
export interface ConfirmedWrite {
  kind: "create_product" | "create_promotion" | "listing_edit" | "price_edit";
  /** The new product's id, the promotion activity id, or the edited product's id. */
  tiktok_id: string | null;
  confirmed_at: string | null;
  discount_pct: number | null;
  /** A listing edit's changed fields: `title` / `description`. */
  fields: string[];
}

/** P71: TikTok's diagnosis of a listing -- the issue count and their short VN labels. */
export interface DiagnosisReading {
  count: number;
  issues: string[];
  read_at: string | null;
}

/** P71: a sandbox listing edit's TikTok diagnosis at Ngày 0 and now; null = not read. */
export interface ListingQuality {
  before: DiagnosisReading | null;
  after: DiagnosisReading | null;
  /** P76-5: "Sau sửa (TikTok kiểm tra)" -- TikTok's check of the draft before the write; null = not read. */
  checked?: DiagnosisReading | null;
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
  /**
   * Fast track P10-B: `photo` / `seller_action` while the run waits for the seller;
   * P14-E content runs: `content_choice` (pick a script) / `content_publish` (film / go LIVE).
   */
  awaiting?: "photo" | "seller_action" | "content_choice" | "content_publish" | null;
  /** Fast track P10 integration: the decision card (`action_cards.id`) the run came from. */
  decision_id?: string | null;
  /**
   * Fast track P61-B (D71.2): the run's writes went to the sandbox merchant, not the
   * seller's shop ("chạy thử"). True only for a run that actually wrote.
   */
  simulated?: boolean;
  /**
   * Fast track P66 (D20-D22): `create` / `promotion` for the sandbox create workflows,
   * else null. The run panel picks its step plan and header from it, also after a reload.
   */
  run_flow?: "create" | "promotion" | null;
  /**
   * Fast track P66: for a sandbox reviewer only, whether the reviewer started this run
   * ("Hoàn tác" is offered only then); null for every other viewer.
   */
  started_by_viewer?: boolean | null;
  /** Fast track P67: sandbox reviewer only -- the run's confirmed TikTok write; null otherwise. */
  confirmed_write?: ConfirmedWrite | null;
  /** P71: sandbox reviewer only -- a listing edit's TikTok diagnosis, Ngày 0 → now. */
  listing_quality?: ListingQuality | null;
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
