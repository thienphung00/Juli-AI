import { Suspense } from "react";

import { AnalysisPageClient } from "../../components/analysis-page-client";

/**
 * Phân tích (AC-8.6, ADR-109 d.2–5): sub-tabs Sản phẩm / Nội dung, stream
 * funnels, the clicked cell's ranking. The KPI dashboard stays one link away
 * at `/analytics/[metricKey]`.
 */
export default function AnalyticsPage() {
  return (
    <Suspense fallback={<p className="text-muted">Đang tải phân tích…</p>}>
      <AnalysisPageClient />
    </Suspense>
  );
}
