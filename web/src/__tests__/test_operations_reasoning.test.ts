/**
 * Issue #180 — Rules-only reasoning copy layer (P1.8-5)
 */
import {
  buildWorkflowReasoning,
  collectIndicatorNumericValues,
  WORKFLOW_REASONING_TEMPLATES,
} from "@/lib/operations/reasoning";
import {
  classifyShopProfile,
  computeHealthCheckResults,
  rankWorkflowRecommendations,
} from "@/lib/operations";
import { loadOperationalModel } from "@/lib/mock-data/operations";
import {
  VALIDATED_WORKFLOW_IDS,
  type ValidatedWorkflowId,
} from "@/lib/mock-data/operations/schemas";
import { HEALTH_INDICATOR_TRACEABILITY_MAP } from "@/lib/operations/health-check";

const WORKFLOW_DISPLAY_NAMES: Record<ValidatedWorkflowId, string> = {
  npl: "Thêm sản phẩm mới",
  minimize_violations: "Giảm thiểu vi phạm",
  budget_optimization: "Tối ưu ngân sách quảng cáo",
  product_scaling: "Mở rộng sản phẩm",
  refund_spike_detection: "Phát hiện đỉnh hoàn tiền",
  stockout_prevention: "Phòng tránh hết hàng",
};

const INVENTED_WORKFLOW_PHRASES = [
  "Growth Copilot",
  "Revenue Leakage Copilot",
  "New Seller Copilot",
  "listing_workflow",
  "inventory_management",
];

function combinedReasoningText(reasoning: ReturnType<typeof buildWorkflowReasoning>): string {
  return [reasoning.why, reasoning.expected_impact, ...reasoning.next_steps].join(" ");
}

/** Signal-derived copy only — next_steps are fixed operational templates (days, cadence). */
function signalDerivedReasoningText(
  reasoning: ReturnType<typeof buildWorkflowReasoning>,
): string {
  return [reasoning.why, reasoning.expected_impact].join(" ");
}

function extractNumbers(text: string): number[] {
  const matches = text.match(/\d+(?:[.,]\d+)?/g) ?? [];
  return matches.map((token) => Number.parseFloat(token.replace(",", ".")));
}

function allowedNumbersForWorkflow(
  workflowId: ValidatedWorkflowId,
  health: ReturnType<typeof computeHealthCheckResults>,
  recommendation: ReturnType<typeof rankWorkflowRecommendations>["recommended_workflows"][number],
): Set<number> {
  const indicatorIds = HEALTH_INDICATOR_TRACEABILITY_MAP;
  const relevantIndicators = Object.entries(indicatorIds)
    .filter(([, workflows]) => workflows.includes(workflowId))
    .map(([id]) => id as keyof typeof health.indicators);

  const allowed = new Set<number>();
  for (const indicatorId of relevantIndicators) {
    for (const value of collectIndicatorNumericValues(health.indicators[indicatorId])) {
      allowed.add(value);
      allowed.add(Math.round(value * 10) / 10);
      allowed.add(Math.round(value));
    }
  }

  allowed.add(recommendation.expected_impact.value);
  allowed.add(Math.round(recommendation.expected_impact.value * 10) / 10);
  allowed.add(Math.round(recommendation.expected_impact.value));

  return allowed;
}

describe("Issue #180: buildWorkflowReasoning envelope", () => {
  it("returns rules copy with why, expected impact, and next steps per workflow", () => {
    const health = computeHealthCheckResults(loadOperationalModel("NEW_SHOP"));
    const recommendation = rankWorkflowRecommendations("NEW_SHOP", health).recommended_workflows[0]!;

    const reasoning = buildWorkflowReasoning(recommendation, health);

    expect(reasoning).toMatchObject({
      copy_source: "rules",
      why: expect.any(String),
      expected_impact: expect.any(String),
      next_steps: expect.arrayContaining([expect.any(String)]),
      source_indicator_ids: expect.any(Array),
    });
    expect(reasoning.next_steps.length).toBeGreaterThanOrEqual(2);
  });

  it("exposes a template entry for every validated workflow_id", () => {
    for (const workflowId of VALIDATED_WORKFLOW_IDS) {
      expect(WORKFLOW_REASONING_TEMPLATES[workflowId]).toBeDefined();
    }
  });
});

describe("Issue #180: reasoning references only health signals", () => {
  for (const profile of ["NEW_SHOP", "MID_LARGE_SHOP"] as const) {
    it(`uses only traceable indicators for ${profile} recommendations`, () => {
      const model = loadOperationalModel(profile);
      const health = computeHealthCheckResults(model);
      const recommendations = rankWorkflowRecommendations(profile, health);

      for (const recommendation of recommendations.recommended_workflows) {
        const reasoning = buildWorkflowReasoning(recommendation, health);
        const allowedIndicators = Object.entries(HEALTH_INDICATOR_TRACEABILITY_MAP)
          .filter(([, workflows]) => workflows.includes(recommendation.workflow_id))
          .map(([id]) => id);

        for (const indicatorId of reasoning.source_indicator_ids) {
          expect(allowedIndicators).toContain(indicatorId);
        }
      }
    });

    it(`does not hallucinate metrics for ${profile} recommendations`, () => {
      const health = computeHealthCheckResults(loadOperationalModel(profile));
      const recommendations = rankWorkflowRecommendations(profile, health);

      for (const recommendation of recommendations.recommended_workflows) {
        const reasoning = buildWorkflowReasoning(recommendation, health);
        const text = signalDerivedReasoningText(reasoning);
        const numbersInCopy = extractNumbers(text);
        const allowed = allowedNumbersForWorkflow(
          recommendation.workflow_id,
          health,
          recommendation,
        );

        for (const value of numbersInCopy) {
          const isAllowed = [...allowed].some(
            (candidate) => Math.abs(candidate - value) < 0.15,
          );
          expect(isAllowed).toBe(true);
        }
      }
    });
  }
});

describe("Issue #180: catalog guard on reasoning copy", () => {
  for (const profile of ["NEW_SHOP", "MID_LARGE_SHOP"] as const) {
    it(`never mentions workflows outside catalog for ${profile}`, () => {
      const health = computeHealthCheckResults(loadOperationalModel(profile));
      const recommendations = rankWorkflowRecommendations(profile, health);

      for (const recommendation of recommendations.recommended_workflows) {
        const reasoning = buildWorkflowReasoning(recommendation, health);
        const text = combinedReasoningText(reasoning);

        const otherWorkflowNames = Object.entries(WORKFLOW_DISPLAY_NAMES)
          .filter(([id]) => id !== recommendation.workflow_id)
          .map(([, name]) => name);

        for (const phrase of [...otherWorkflowNames, ...INVENTED_WORKFLOW_PHRASES]) {
          expect(text).not.toContain(phrase);
        }

        for (const workflowId of VALIDATED_WORKFLOW_IDS) {
          if (workflowId !== recommendation.workflow_id) {
            expect(text).not.toContain(workflowId);
          }
        }
      }
    });
  }
});

describe("Issue #180: classify → health → rank → reasoning chain", () => {
  it("produces Vietnamese copy with copy_source rules for pipeline output", () => {
    const model = loadOperationalModel("MID_LARGE_SHOP");
    const profile = classifyShopProfile(model);
    const health = computeHealthCheckResults(model);
    const top = rankWorkflowRecommendations(profile, health).recommended_workflows[0]!;

    const reasoning = buildWorkflowReasoning(top, health);

    expect(reasoning.copy_source).toBe("rules");
    expect(reasoning.why.length).toBeGreaterThan(10);
    expect(/[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i.test(
      combinedReasoningText(reasoning),
    )).toBe(true);
  });
});
