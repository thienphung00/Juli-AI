import { AnalyticsDashboard } from "../../../components/analytics-dashboard";

interface AnalyticsMetricPageProps {
  params: Promise<{ metricKey: string }>;
}

export default async function AnalyticsMetricPage({
  params,
}: AnalyticsMetricPageProps) {
  const { metricKey } = await params;

  return <AnalyticsDashboard metricKey={metricKey} />;
}
