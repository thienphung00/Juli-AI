import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import { formatNumber } from "@/lib/format";
import type { HealthCheckResults } from "@/lib/operations/health-check";
import type { WorkflowRecommendation } from "@/lib/operations/recommendations";

import { buildDecisionAnalytics } from "./detail-content";

export interface DecisionChatContext {
  workflow_id: ValidatedWorkflowId;
  title: string;
  rationale: string;
  impact_metric: string;
  impact_value: number;
  confidence: WorkflowRecommendation["expected_impact"]["confidence"];
  health_signal: string;
}

const WORKFLOW_SUGGESTED_PROMPTS: Record<ValidatedWorkflowId, string[]> = {
  npl: [
    "Giải thích đề xuất này",
    "Sản phẩm nào nên thêm trước?",
    "So sánh sản phẩm",
  ],
  minimize_violations: [
    "Giải thích đề xuất này",
    "Vi phạm nào cần xử lý trước?",
    "Rủi ro nếu không hành động?",
  ],
  budget_optimization: [
    "Giải thích đề xuất này",
    "Tại sao ROAS thấp?",
    "Nên điều chỉnh ngân sách thế nào?",
  ],
  product_scaling: [
    "Giải thích đề xuất này",
    "So sánh sản phẩm",
    "SKU nào có tiềm năng mở rộng?",
  ],
  refund_spike_detection: [
    "Giải thích đề xuất này",
    "Tại sao tỷ lệ hoàn tiền tăng?",
    "Rủi ro nếu không xử lý?",
  ],
  stockout_prevention: [
    "Giải thích đề xuất này",
    "SKU nào sắp hết hàng?",
    "Ảnh hưởng doanh thu nếu hết hàng?",
  ],
};

function primaryHealthSignal(
  recommendation: WorkflowRecommendation,
  health: HealthCheckResults,
): string {
  const analytics = buildDecisionAnalytics(recommendation, health);
  const primary = analytics[0];
  if (!primary) {
    return recommendation.rationale;
  }

  const trend = primary.trend ? ` (${primary.trend})` : "";
  return `${primary.label}: ${primary.value}${trend}`;
}

export function buildDecisionChatContext(
  recommendation: WorkflowRecommendation,
  health: HealthCheckResults,
): DecisionChatContext {
  return {
    workflow_id: recommendation.workflow_id,
    title: recommendation.workflow_name,
    rationale: recommendation.rationale,
    impact_metric: recommendation.expected_impact.metric,
    impact_value: recommendation.expected_impact.value,
    confidence: recommendation.expected_impact.confidence,
    health_signal: primaryHealthSignal(recommendation, health),
  };
}

export function buildContextualSuggestedPrompts(context: DecisionChatContext): string[] {
  return [...WORKFLOW_SUGGESTED_PROMPTS[context.workflow_id]];
}

export function buildDefaultDecisionPrompts(
  recommendation: WorkflowRecommendation,
): string[] {
  const workflowPrompts = WORKFLOW_SUGGESTED_PROMPTS[recommendation.workflow_id];
  return [
    `Giải thích đề xuất "${recommendation.workflow_name}"`,
    ...workflowPrompts.slice(1),
  ];
}

export function buildDecisionAwareWelcome(context: DecisionChatContext): string {
  return `Mình đang xem đề xuất "${context.title}" cùng bạn. Hỏi mình về lý do, tín hiệu sức khỏe shop (${context.health_signal}), hoặc bước tiếp theo nhé.`;
}

export function buildTopDecisionWelcome(recommendation: WorkflowRecommendation): string {
  return `Đề xuất ưu tiên nhất hiện tại là "${recommendation.workflow_name}". Hỏi mình về lý do, tác động dự kiến, hoặc cách hoàn tất đề xuất này nhé.`;
}

export function buildDecisionAwareMockReply(
  context: DecisionChatContext,
  userText: string,
): string {
  const normalized = userText.trim();

  if (/giải thích|đề xuất này|tại sao đề xuất/i.test(normalized)) {
    return `Đề xuất "${context.title}" được đưa ra vì ${context.rationale} Tín hiệu sức khỏe shop: ${context.health_signal}. Tác động dự kiến — ${context.impact_metric}: ${formatNumber(context.impact_value)}.`;
  }

  if (/roas|ngân sách|quảng cáo/i.test(normalized) && context.workflow_id === "budget_optimization") {
    return `Với "${context.title}", ${context.health_signal}. Điều chỉnh ngân sách theo đề xuất này nhằm đưa ROAS về mục tiêu và giảm chi tiêu lãng phí trên chiến dịch dưới chuẩn.`;
  }

  if (/so sánh|sản phẩm|sku/i.test(normalized)) {
    return `Trong bối cảnh "${context.title}", mình ưu tiên SKU có tín hiệu tăng trưởng mạnh nhất từ pipeline mock. ${context.health_signal}. Bạn có thể hỏi thêm về từng sản phẩm cụ thể.`;
  }

  if (/hoàn tiền|refund/i.test(normalized)) {
    return `"${context.title}" liên quan đến ${context.health_signal}. Xử lý sớm giúp giảm rò rỉ doanh thu trước khi tỷ lệ hoàn tiền leo thang.`;
  }

  if (/hết hàng|tồn kho|stock/i.test(normalized)) {
    return `"${context.title}" dựa trên ${context.health_signal}. Bổ sung tồn kho đúng lúc tránh mất đơn cuối tuần.`;
  }

  return `Về đề xuất "${context.title}": ${context.health_signal}. ${context.impact_metric} dự kiến ${formatNumber(context.impact_value)}. Bạn muốn đi sâu vào lý do, số liệu, hay bước thực hiện?`;
}

export function isWorkflowSpecificPrompt(prompt: string, workflowId: ValidatedWorkflowId): boolean {
  const workflowPrompts = WORKFLOW_SUGGESTED_PROMPTS[workflowId];
  return workflowPrompts.some(
    (chip) => prompt === chip || prompt.includes(workflowPrompts[0]),
  );
}
