import { DestinationPlaceholder } from "../../../components/destination-placeholder";

interface AnalyticsMetricPageProps {
  params: Promise<{ metricKey: string }>;
}

export default async function AnalyticsMetricPage({
  params,
}: AnalyticsMetricPageProps) {
  const { metricKey } = await params;

  return (
    <DestinationPlaceholder
      description="Chi tiết KPI cho chỉ số này sẽ được bổ sung trong lát cắt Phân tích. Demo không hiển thị số liệu giả tại đây."
      title={`Phân tích — ${metricKey}`}
    />
  );
}
