import { AnalysisPageClient } from "../../components/analysis-page-client";

/**
 * Phân tích (D21, AC-7.7): the shop diagnosis report. The earlier KPI
 * dashboard stays one link away at `/analytics/[metricKey]`.
 */
export default function AnalyticsPage() {
  return <AnalysisPageClient />;
}
