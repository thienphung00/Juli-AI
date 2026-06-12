/**
 * Issue #192 — Decision view-model (P1.8-9)
 */
import {
  classifyShopProfile,
  computeHealthCheckResults,
  rankWorkflowRecommendations,
} from "@/lib/operations";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";
import { loadOperationalModel } from "@/lib/mock-data/operations";
import {
  applyDecisionLifecycle,
  InvalidWorkflowIdError,
  isValidatedWorkflowId,
  sortDecisionsByImpact,
  takeTopDecisions,
  toDecision,
  toDecisionsFromRecommendations,
} from "@/lib/decisions";

function sampleRecommendation(
  overrides: Partial<WorkflowRecommendation> = {},
): WorkflowRecommendation {
  return {
    workflow_id: "npl",
    workflow_name: "Thêm sản phẩm mới",
    priority: 1,
    rationale: "SPS còn thiếu 12 điểm so với ngưỡng tốt nghiệp.",
    expected_impact: {
      metric: "SPS",
      value: 12,
      confidence: "high",
    },
    preconditions_met: true,
    user_action_required: true,
    ...overrides,
  };
}

describe("Issue #192: toDecision()", () => {
  it("maps a workflow_recommendation envelope to a Decision", () => {
    const recommendation = sampleRecommendation();
    const decision = toDecision(recommendation);

    expect(decision).toEqual({
      id: "npl",
      workflow_id: "npl",
      title: "Thêm sản phẩm mới",
      estimated_impact: {
        metric: "SPS",
        value: 12,
      },
      confidence: "high",
      reasoning_summary: "SPS còn thiếu 12 điểm so với ngưỡng tốt nghiệp.",
      required_inputs: expect.arrayContaining([
        expect.objectContaining({
          key: "product_selection",
          required: true,
        }),
      ]),
      status: "recommended",
    });
  });

  it("rejects unknown workflow_id values", () => {
    const invalid = sampleRecommendation({
      workflow_id: "unknown_workflow" as WorkflowRecommendation["workflow_id"],
    });

    expect(() => toDecision(invalid)).toThrow(InvalidWorkflowIdError);
  });
});

describe("Issue #192: takeTopDecisions()", () => {
  it("returns the three highest-impact decisions only", () => {
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const ranked = rankWorkflowRecommendations("MID_LARGE_SHOP", health);
    const decisions = toDecisionsFromRecommendations(ranked.recommended_workflows);
    const topThree = takeTopDecisions(decisions, 3);

    expect(topThree).toHaveLength(3);

    const sorted = sortDecisionsByImpact(decisions);
    expect(topThree.map((item) => item.id)).toEqual(sorted.slice(0, 3).map((item) => item.id));

    for (let index = 0; index < topThree.length - 1; index += 1) {
      expect(topThree[index]!.estimated_impact.value).toBeGreaterThanOrEqual(
        topThree[index + 1]!.estimated_impact.value,
      );
    }
  });
});

describe("Issue #192: catalog guard", () => {
  it("filters invalid workflow_id values when mapping recommendation batches", () => {
    const valid = sampleRecommendation({ workflow_id: "npl", priority: 1 });
    const invalid = sampleRecommendation({
      workflow_id: "ghost_workflow" as WorkflowRecommendation["workflow_id"],
      priority: 99,
    });

    const decisions = toDecisionsFromRecommendations([valid, invalid]);

    expect(decisions).toHaveLength(1);
    expect(decisions[0]?.workflow_id).toBe("npl");
  });

  it("exposes isValidatedWorkflowId for catalog checks", () => {
    expect(isValidatedWorkflowId("refund_spike_detection")).toBe(true);
    expect(isValidatedWorkflowId("not_a_workflow")).toBe(false);
  });
});

describe("Issue #192: applyDecisionLifecycle()", () => {
  it("merges approval session disposition into decision status", () => {
    const decision = toDecision(sampleRecommendation());

    expect(
      applyDecisionLifecycle(decision, {
        disposition: "pending",
        userActionRequired: true,
      }).status,
    ).toBe("recommended");

    expect(
      applyDecisionLifecycle(decision, {
        disposition: "approved",
        userActionRequired: true,
        inputsCollected: false,
      }).status,
    ).toBe("needs_input");

    expect(
      applyDecisionLifecycle(decision, {
        disposition: "approved",
        userActionRequired: true,
        inputsCollected: true,
        executorStatus: "executing",
      }).status,
    ).toBe("executing");

    expect(
      applyDecisionLifecycle(decision, {
        disposition: "approved",
        userActionRequired: false,
        executorStatus: "completed",
      }).status,
    ).toBe("completed");
  });
});

describe("Issue #192: integration with operations pipeline", () => {
  it("maps ranked NEW_SHOP recommendations into decision envelopes", () => {
    const model = loadOperationalModel("NEW_SHOP");
    const profile = classifyShopProfile(model);
    const health = computeHealthCheckResults(model);
    const ranked = rankWorkflowRecommendations(profile, health);
    const decisions = toDecisionsFromRecommendations(ranked.recommended_workflows);

    expect(decisions.length).toBeGreaterThan(0);
    for (const decision of decisions) {
      expect(isValidatedWorkflowId(decision.workflow_id)).toBe(true);
      expect(decision.status).toBe("recommended");
      expect(decision.title.length).toBeGreaterThan(0);
      expect(decision.reasoning_summary.length).toBeGreaterThan(0);
    }
  });
});
