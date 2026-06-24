/**
 * Issue #199 — Juli Chat decision context (contextual prompts + decision-aware replies)
 */
import {
  buildContextualSuggestedPrompts,
  buildDecisionAwareMockReply,
  buildDecisionChatContext,
  buildDefaultDecisionPrompts,
  isWorkflowSpecificPrompt,
} from "@/lib/decisions/chat-context";
import { runOperationsPipeline } from "@/lib/operations/use-operations-pipeline";

describe("Issue #199: decision chat context (pure)", () => {
  const pipeline = runOperationsPipeline("new");
  const recommendation = pipeline.workflowRecommendations.recommended_workflows[0]!;

  it("builds contextual prompts with at least one workflow-specific chip", () => {
    const context = buildDecisionChatContext(recommendation, pipeline.healthResults);
    const prompts = buildContextualSuggestedPrompts(context);

    expect(prompts.length).toBeGreaterThanOrEqual(3);
    expect(prompts[0]).toBe("Giải thích đề xuất này");
    expect(isWorkflowSpecificPrompt(prompts[1]!, context.workflow_id)).toBe(true);
  });

  it("builds default decision-oriented prompts from top recommendation", () => {
    const prompts = buildDefaultDecisionPrompts(recommendation);

    expect(prompts[0]).toContain(recommendation.workflow_name);
    expect(prompts.some((p) => p.includes("ROAS") || p.includes("sản phẩm") || p.includes("hoàn tiền") || p.includes("hết hàng") || p.includes("vi phạm"))).toBe(true);
    expect(prompts).not.toContain("Creator nào nên đẩy tối nay?");
  });

  it("mock reply mentions decision title and health signal when context present", () => {
    const context = buildDecisionChatContext(recommendation, pipeline.healthResults);
    const reply = buildDecisionAwareMockReply(context, "Giải thích đề xuất này");

    expect(reply).toContain(context.title);
    expect(reply).toContain(context.health_signal);
    expect(reply).toContain(context.impact_metric);
  });
});
