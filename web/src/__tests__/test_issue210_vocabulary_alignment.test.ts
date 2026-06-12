/**
 * Issue #210 — Align AI Chat and Reports copy with seller vocabulary system
 */
import {
  buildContextualSuggestedPrompts,
  buildDecisionAwareMockReply,
  buildDecisionAwareWelcome,
  buildDecisionChatContext,
  buildDefaultDecisionPrompts,
  buildTopDecisionWelcome,
} from "@/lib/decisions/chat-context";
import { buildDecisionAnalytics } from "@/lib/decisions/detail-content";
import { AHR_METRIC, SPS_METRIC } from "@/lib/metrics/shop-health-metrics";
import { buildWorkflowReasoning } from "@/lib/operations/reasoning";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

const SELLER_CONFIDENCE_PATTERNS = [/độ tin cậy/i, /confidence/i];

function assertNoSellerConfidenceCopy(text: string): void {
  for (const pattern of SELLER_CONFIDENCE_PATTERNS) {
    expect(text).not.toMatch(pattern);
  }
}

describe("Issue #210: seller vocabulary alignment", () => {
  const pipeline = runOperationsPipeline("new");
  const recommendation = pipeline.workflowRecommendations.recommended_workflows[0]!;
  const context = buildDecisionChatContext(recommendation, pipeline.healthResults);

  it("chat suggested prompts use đề xuất vocabulary", () => {
    const contextual = buildContextualSuggestedPrompts(context);
    const defaults = buildDefaultDecisionPrompts(recommendation);

    expect(contextual[0]).toBe("Giải thích đề xuất này");
    expect(defaults[0]).toMatch(/^Giải thích đề xuất "/);
    expect(contextual.join(" ")).not.toMatch(/quyết định này/i);
  });

  it("chat welcome and mock replies omit confidence labels", () => {
    assertNoSellerConfidenceCopy(buildDecisionAwareWelcome(context));
    assertNoSellerConfidenceCopy(buildTopDecisionWelcome(recommendation));

    const reply = buildDecisionAwareMockReply(context, "Giải thích đề xuất này");
    assertNoSellerConfidenceCopy(reply);
    expect(reply).toMatch(/được đưa ra vì/i);
    expect(reply).toContain(context.title);
  });

  it("reasoning expected_impact omits confidence labels", () => {
    const reasoning = buildWorkflowReasoning(recommendation, pipeline.healthResults);
    assertNoSellerConfidenceCopy(reasoning.expected_impact);
    expect(reasoning.expected_impact).toMatch(/Dự kiến cải thiện/);
  });

  it("decision analytics use canonical SPS label for npl workflow", () => {
    const npl = pipeline.workflowRecommendations.recommended_workflows.find(
      (item) => item.workflow_id === "npl",
    );
    if (!npl) {
      return;
    }

    const metrics = buildDecisionAnalytics(npl, pipeline.healthResults);
    const spsMetric = metrics.find((metric) => metric.key === "sps");
    expect(spsMetric?.label).toContain(SPS_METRIC.label);
    expect(metrics.every((metric) => !/độ tin cậy/i.test(metric.trend ?? ""))).toBe(true);
  });

  it("decision analytics default branch omits confidence trend", () => {
    const scaling = pipeline.workflowRecommendations.recommended_workflows.find(
      (item) => item.workflow_id === "product_scaling",
    );
    if (!scaling) {
      return;
    }

    const metrics = buildDecisionAnalytics(scaling, pipeline.healthResults);
    expect(metrics.every((metric) => !/độ tin cậy/i.test(metric.trend ?? ""))).toBe(true);
  });

  it("canonical health metric labels are SPS and AHR", () => {
    expect(SPS_METRIC.label).toBe("SPS");
    expect(AHR_METRIC.label).toBe("AHR");
  });
});
