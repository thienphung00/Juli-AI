/**
 * TypeScript mirror of the Demo Decisions envelope (ADR-084 decision 3, issue #1309).
 *
 * Mirrors `backend/src/juli_backend/api/routes/demo_decisions.py:DemoDecisionItem`
 * field-for-field. The `is_executable` discriminator reveals whether Juli can carry
 * this recommendation out itself, derived from the real playbook registry, without
 * exposing `workflow_key` or any other workflow taxonomy. `workflow_key` never
 * appears in this envelope, per the no-PII/no-raw-payload discipline
 * (#718 AC3 / `_build_masked_item`'s docstring).
 *
 * Two independent guards against drift, at two layers:
 *  - Interfaces (this module, e.g. `DemoDecisionItem`) -- what a consumer actually
 *    imports and types against. TypeScript types are erased at runtime, so the guard
 *    here is `tsc` itself: a future Pydantic change that adds/removes a field will
 *    fail compilation if this interface is not updated to match.
 *  - Runtime validation layer: a cross-language contract test proves both sides
 *    (Pydantic and TypeScript) deserialize the same golden envelope fixtures.
 */

export interface DemoDecisionExpectedImpact {
  metric: string;
  value: number;
  confidence: string;
}

export interface DemoDecisionReasoning {
  copy_source?: string | null;
  why?: string | null;
  expected_impact?: string | null;
  next_steps: string[];
  source_kpi_ids: string[];
}

export interface DemoDecisionRecommendation {
  workflow_name?: string | null;
  priority?: number | null;
  rationale?: string | null;
  expected_impact?: DemoDecisionExpectedImpact | null;
  preconditions_met?: boolean | null;
  user_action_required?: boolean | null;
  source_kpi_ids: string[];
  reasoning?: DemoDecisionReasoning | null;
}

export interface DemoDecisionItem {
  id: string;
  title: string;
  description: string;
  severity: string;
  priority: number;
  computed_at: string | null;
  surfaced_at: string | null;
  is_executable: boolean;
  recommendation: DemoDecisionRecommendation;
}

export interface DemoDecisionListResponse {
  success: boolean;
  data: DemoDecisionItem[];
  error: string | null;
}

export interface DemoDecisionDetailResponse {
  success: boolean;
  data: DemoDecisionItem | null;
  error: string | null;
}

/**
 * Golden fixture for cross-language contract testing (ADR-084 decision 3).
 * Both Pydantic (Python) and TypeScript consumers must successfully deserialize
 * this envelope, proving they agree on the field set and structure.
 *
 * This fixture reflects a real executability state: `is_executable: true`
 * for a card whose workflow_key resolves to a registered playbook
 * (e.g., "optimize_product_2").
 */
export const GOLDEN_DEMO_DECISION_EXECUTABLE: DemoDecisionItem = {
  id: "00000000-0000-0000-0000-000000000001",
  title: "Optimize this listing",
  description: "CTR fell 18% week over week on this listing.",
  severity: "high",
  priority: 1,
  computed_at: "2026-08-08T08:00:00+00:00",
  surfaced_at: "2026-08-08T08:05:00+00:00",
  is_executable: true,
  recommendation: {
    workflow_name: "Optimize Product",
    priority: 1,
    rationale: "Price optimization can improve margin.",
    expected_impact: {
      metric: "gmv",
      value: 1.05,
      confidence: "medium",
    },
    preconditions_met: true,
    user_action_required: true,
    source_kpi_ids: ["gmv_trend"],
    reasoning: {
      copy_source: "rules",
      why: "CTR down, price up.",
      expected_impact: "Higher listing visibility and margin.",
      next_steps: ["Review pricing"],
      source_kpi_ids: ["gmv_trend"],
    },
  },
};

/**
 * Golden fixture for a non-executable card: `is_executable: false` for a card
 * whose workflow_key has no registered playbook (e.g., "future_workflow_1").
 */
export const GOLDEN_DEMO_DECISION_NON_EXECUTABLE: DemoDecisionItem = {
  id: "00000000-0000-0000-0000-000000000002",
  title: "Fulfill pending orders",
  description: "10 orders pending fulfillment.",
  severity: "warning",
  priority: 2,
  computed_at: "2026-08-08T09:00:00+00:00",
  surfaced_at: "2026-08-08T09:05:00+00:00",
  is_executable: false,
  recommendation: {
    workflow_name: "Fulfill Orders",
    priority: 2,
    rationale: "Speed up order delivery.",
    expected_impact: {
      metric: "fulfillment_speed",
      value: 1.2,
      confidence: "high",
    },
    preconditions_met: true,
    user_action_required: false,
    source_kpi_ids: ["pending_orders"],
    reasoning: {
      copy_source: "rules",
      why: "Orders pending > threshold.",
      expected_impact: "Faster delivery, happier customers.",
      next_steps: [],
      source_kpi_ids: ["pending_orders"],
    },
  },
};
