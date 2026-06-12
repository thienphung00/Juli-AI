import type { WorkflowRecommendation } from "./recommendations";

export interface RecentProgressItem {
  id: string;
  title: string;
  whatChanged: string;
  whyChanged: string;
  resultSummary: string;
}

/**
 * Weekly-style transparent reporting for the Home Recent Progress section (P1.8).
 */
export function buildRecentProgressItems(
  recommendations: WorkflowRecommendation[],
): RecentProgressItem[] {
  const top = recommendations.slice(0, 2);

  return top.map((recommendation) => ({
    id: recommendation.workflow_id,
    title: recommendation.workflow_name,
    whatChanged: `${recommendation.expected_impact.metric} dự kiến ${recommendation.expected_impact.value >= 0 ? "+" : ""}${recommendation.expected_impact.value} điểm`,
    whyChanged: recommendation.rationale,
    resultSummary: "Báo cáo tuần sẽ cập nhật sau khi bạn phê duyệt và thực hiện đề xuất.",
  }));
}
