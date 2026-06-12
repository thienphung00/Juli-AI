/**
 * Issue #179 — Workflow recommendation ranking (P1.8-4)
 */
import {
  MID_LARGE_IMPACT_THRESHOLD_VND,
  rankWorkflowRecommendations,
} from "@/lib/operations/recommendations";
import {
  classifyShopProfile,
  computeHealthCheckResults,
} from "@/lib/operations";
import { loadOperationalModel } from "@/lib/mock-data/operations";
import {
  VALIDATED_WORKFLOW_IDS,
  type ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";

const GROWTH_LOSS_WORKFLOWS: ValidatedWorkflowId[] = [
  "budget_optimization",
  "product_scaling",
  "refund_spike_detection",
  "stockout_prevention",
];

const PROBATION_WORKFLOWS: ValidatedWorkflowId[] = ["npl", "minimize_violations"];

describe("Issue #179: rankWorkflowRecommendations envelope", () => {
  it("returns typed workflow_recommendations with shop_profile and ranked items", () => {
    const health = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const result = rankWorkflowRecommendations("NEW_SHOP", health);

    expect(result.shop_profile).toBe("NEW_SHOP");
    expect(result.recommended_workflows.length).toBeGreaterThan(0);
    expect(result.recommended_workflows[0]).toMatchObject({
      workflow_id: expect.any(String),
      workflow_name: expect.any(String),
      priority: 1,
      rationale: expect.any(String),
      expected_impact: {
        metric: expect.any(String),
        value: expect.any(Number),
        confidence: expect.stringMatching(/^(high|medium|low)$/),
      },
      preconditions_met: expect.any(Boolean),
      user_action_required: expect.any(Boolean),
    });
  });

  it("assigns contiguous priority ranks starting at 1", () => {
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const result = rankWorkflowRecommendations("MID_LARGE_SHOP", health);
    const priorities = result.recommended_workflows.map((item) => item.priority);

    expect(priorities).toEqual(
      Array.from({ length: priorities.length }, (_, index) => index + 1),
    );
  });
});

describe("Issue #179: NEW_SHOP profile gating and ordering", () => {
  it("recommends only probation workflows for NEW_SHOP", () => {
    const health = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const result = rankWorkflowRecommendations("NEW_SHOP", health);
    const workflowIds = result.recommended_workflows.map((item) => item.workflow_id);

    expect(workflowIds).toEqual(expect.arrayContaining(PROBATION_WORKFLOWS));
    for (const workflowId of GROWTH_LOSS_WORKFLOWS) {
      expect(workflowIds).not.toContain(workflowId);
    }
  });

  it("ranks minimize_violations ahead of npl when AHR gap is critical and violations exist", () => {
    const model = loadOperationalModel("NEW_SHOP");
    const health = computeHealthCheckResults({
      ...model,
      probation: model.probation
        ? {
            ...model.probation,
            ahr_current: 60,
            ahr_threshold: 90,
            violations: [
              {
                violation_id: "viol_critical",
                category: "Late shipment",
                count: 5,
                severity: "high",
              },
            ],
          }
        : null,
    });

    const result = rankWorkflowRecommendations("NEW_SHOP", health);
    expect(result.recommended_workflows[0]?.workflow_id).toBe("minimize_violations");
  });
});

describe("Issue #179: MID_LARGE_SHOP ranking", () => {
  it("recommends only growth and loss-prevention workflows for MID_LARGE_SHOP", () => {
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const result = rankWorkflowRecommendations("MID_LARGE_SHOP", health);
    const workflowIds = result.recommended_workflows.map((item) => item.workflow_id);

    expect(workflowIds).toEqual(expect.arrayContaining(GROWTH_LOSS_WORKFLOWS));
    for (const workflowId of PROBATION_WORKFLOWS) {
      expect(workflowIds).not.toContain(workflowId);
    }
  });

  it("ranks refund_spike_detection first when spike is detected on fixture", () => {
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    expect(health.indicators.refund_spike_indicator.spike_detected).toBe(true);

    const result = rankWorkflowRecommendations("MID_LARGE_SHOP", health);
    expect(result.recommended_workflows[0]?.workflow_id).toBe("refund_spike_detection");
  });
});

describe("Issue #179: profile gating ordering and precondition flags", () => {
  it("profile gating ordering and precondition flags per shop profile", () => {
    const newHealth = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const newResult = rankWorkflowRecommendations("NEW_SHOP", newHealth);
    expect(newResult.recommended_workflows.map((item) => item.workflow_id)).toEqual(
      expect.arrayContaining(PROBATION_WORKFLOWS),
    );

    const midHealth = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const midResult = rankWorkflowRecommendations("MID_LARGE_SHOP", midHealth);
    expect(midResult.recommended_workflows[0]?.workflow_id).toBe("refund_spike_detection");
    expect(
      midResult.recommended_workflows.find((item) => item.workflow_id === "refund_spike_detection")
        ?.preconditions_met,
    ).toBe(true);
  });
});

describe("Issue #179: precondition flags", () => {
  it("marks refund spike preconditions met when spike_detected is true", () => {
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const refund = rankWorkflowRecommendations("MID_LARGE_SHOP", health).recommended_workflows.find(
      (item) => item.workflow_id === "refund_spike_detection",
    );

    expect(refund?.preconditions_met).toBe(true);
  });

  it("marks npl preconditions met when products exist on NEW_SHOP fixture", () => {
    const health = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const npl = rankWorkflowRecommendations("NEW_SHOP", health).recommended_workflows.find(
      (item) => item.workflow_id === "npl",
    );

    expect(npl?.preconditions_met).toBe(true);
  });
});

describe("Issue #179: catalog guard", () => {
  it("never references workflow IDs outside the validated catalog", () => {
    for (const profile of ["NEW_SHOP", "MID_LARGE_SHOP"] as const) {
      const health = computeHealthCheckResults(loadOperationalModel(profile));
      const result = rankWorkflowRecommendations(profile, health);

      for (const item of result.recommended_workflows) {
        expect(VALIDATED_WORKFLOW_IDS).toContain(item.workflow_id);
      }
    }
  });
});

describe("Issue #179: MID_LARGE impact threshold (optional/TBD)", () => {
  it("documents impact threshold as unset until Product records value in EXECUTION.md", () => {
    expect(MID_LARGE_IMPACT_THRESHOLD_VND).toBeNull();
  });

  it("ranks all eligible workflows when impact threshold is unset", () => {
    const health = computeHealthCheckResults(loadOperationalModel("MID_LARGE_SHOP"));
    const result = rankWorkflowRecommendations("MID_LARGE_SHOP", health);

    expect(result.recommended_workflows).toHaveLength(GROWTH_LOSS_WORKFLOWS.length);
  });
});

describe("Issue #179: classify → health → rank chain", () => {
  it("produces consistent profile between classifier and recommendations envelope", () => {
    const model = loadOperationalModel("NEW_SHOP");
    const profile = classifyShopProfile(model);
    const health = computeHealthCheckResults(model);
    const result = rankWorkflowRecommendations(profile, health);

    expect(result.shop_profile).toBe(profile);
  });
});
