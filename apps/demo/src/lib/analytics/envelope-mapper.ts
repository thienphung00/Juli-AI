import {
  GMV_TIKTOK_ENVELOPE_KEY,
  GMV_TIKTOK_LABEL,
  assertNoNetRevenueAlias,
  isAnalyticsKpiAvailable,
  type AnalyticsKpiEntry,
  type DemoAnalyticsEnvelope,
} from "@juli/contracts";
import type { ChartTrend } from "@juli/ui";
import { formatDateTime, formatNumber, formatVND } from "@juli/utils";

import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../workflows/optimize-product/review";
import type { AnalyticsRange, MetricKey } from "./main-kpis";
import type { KpiSnapshot, KpiTimePoint } from "./mock-data";

const METRIC_TO_ENVELOPE_KEY: Record<MetricKey, string> = {
  "gmv-tiktok": GMV_TIKTOK_ENVELOPE_KEY,
  aov: "aov",
  ctor: "ctor",
  "live-hours": "live_hours",
  "cancellation-rate": "cancellation_rate",
};

export interface SupplementaryChartSnapshot {
  envelopeKey: "product_funnel" | "live_performance";
  label: string;
  formattedValue: string;
  delta: string;
  trend: ChartTrend;
  timeSeries: readonly KpiTimePoint[];
  dataSource: string;
  lastUpdated: string;
}

function computeDelta(series: readonly { v: number }[]): {
  delta: string;
  trend: ChartTrend;
} {
  if (series.length < 2) {
    return { delta: "—", trend: "neutral" };
  }

  const first = series[0]!.v;
  const last = series[series.length - 1]!.v;

  if (first === 0) {
    return { delta: "—", trend: "neutral" };
  }

  const pct = Math.round(((last - first) / Math.abs(first)) * 100);
  const trend: ChartTrend = pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral";
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "—";
  return {
    delta: `${arrow} ${Math.abs(pct)}%`,
    trend,
  };
}

function seriesToTimePoints(
  entry: AnalyticsKpiEntry,
): readonly KpiTimePoint[] {
  if (!entry.series?.length) {
    return [];
  }

  return entry.series.map((point, index) => ({
    label: `T${index + 1}`,
    value: point.v,
  }));
}

function formatKpiValue(
  metricKey: MetricKey,
  value: number,
  currency: string,
): string {
  switch (metricKey) {
    case "gmv-tiktok":
    case "aov":
      return formatVND(value);
    case "ctor":
    case "cancellation-rate":
      return `${formatNumber(value)}%`;
    case "live-hours":
      return `${formatNumber(value)} giờ`;
    default:
      return currency === "VND" ? formatVND(value) : formatNumber(value);
  }
}

function metricSignal(metricKey: MetricKey, trend: ChartTrend): string {
  switch (metricKey) {
    case "gmv-tiktok":
      return trend === "positive"
        ? "GMV TikTok tăng mạnh → cơ hội tăng trưởng → xem xét mở rộng sản phẩm chủ lực"
        : "GMV TikTok giảm → rủi ro doanh thu → xem xét tối ưu sản phẩm";
    case "aov":
      return trend === "positive"
        ? "AOV tăng → giá trị đơn hàng cải thiện → xem xét chiến lược sản phẩm"
        : "AOV giảm → rủi ro giá trị → xem xét sắp xếp lại danh mục";
    case "ctor":
      return trend === "positive"
        ? "CTOR tăng → hiệu suất sản phẩm cải thiện → tiếp tục tối ưu hóa"
        : "CTOR giảm → hiệu suất sản phẩm giảm → xem xét tối ưu sản phẩm";
    case "live-hours":
      return trend === "positive"
        ? "LIVE hours tăng → tương tác người dùng tăng → xem xét mở rộng lịch phát sóng"
        : "LIVE hours giảm → tương tác người dùng giảm → xem xét tối ưu lịch phát sóng";
    case "cancellation-rate":
      return trend === "negative"
        ? "Tỷ lệ hủy đơn giảm → chất lượng đơn hàng cải thiện → duy trì quy trình hiện tại"
        : "Tỷ lệ hủy đơn tăng → rủi ro hủy tăng → kiểm tra quy trình xử lý đơn";
    default:
      return "Thay đổi KPI đáng chú ý trong khoảng thời gian đang chọn.";
  }
}

function metricWorkflow(metricKey: MetricKey): {
  workflowId?: string;
  decisionLabel?: string;
} {
  switch (metricKey) {
    case "gmv-tiktok":
      return {
        workflowId: OPTIMIZE_PRODUCT_WORKFLOW_KEY,
        decisionLabel: "Xem đề xuất tối ưu sản phẩm",
      };
    default:
      return {};
  }
}

export function getEnvelopeKpiEntry(
  envelope: DemoAnalyticsEnvelope | null | undefined,
  metricKey: MetricKey,
): AnalyticsKpiEntry | undefined {
  if (!envelope) {
    return undefined;
  }

  const envelopeKey = METRIC_TO_ENVELOPE_KEY[metricKey];
  if (!envelopeKey) {
    return undefined;
  }

  return envelope.kpis[envelopeKey];
}

export function isMetricLiveAvailable(
  envelope: DemoAnalyticsEnvelope | null | undefined,
  metricKey: MetricKey,
): boolean {
  const entry = getEnvelopeKpiEntry(envelope, metricKey);
  return isAnalyticsKpiAvailable(entry) && Boolean(entry.series?.length);
}

export function isSelectableMetricKey(
  key: string,
  envelope?: DemoAnalyticsEnvelope | null,
): key is MetricKey {
  // Only allow the five Demo Main KPIs (ADR-049 DUX-2)
  if (!Object.hasOwn(METRIC_TO_ENVELOPE_KEY, key as MetricKey)) {
    return false;
  }

  // All five are envelope-backed, so check availability
  return isMetricLiveAvailable(envelope, key as MetricKey);
}

export function buildLiveKpiSnapshot(
  envelope: DemoAnalyticsEnvelope,
  metricKey: MetricKey,
  range: AnalyticsRange,
): KpiSnapshot | null {
  assertNoNetRevenueAlias(envelope);

  const entry = getEnvelopeKpiEntry(envelope, metricKey);
  if (!isAnalyticsKpiAvailable(entry) || !entry.series?.length) {
    return null;
  }

  const timeSeries = seriesToTimePoints(entry);
  const values = entry.series.map((point) => point.v);
  const latestValue = values[values.length - 1]!;
  const { delta, trend } = computeDelta(entry.series);
  const workflow = metricWorkflow(metricKey);

  return {
    formattedValue: formatKpiValue(metricKey, latestValue, envelope.currency),
    delta,
    trend,
    signal: metricSignal(metricKey, trend),
    dataSource:
      metricKey === "gmv-tiktok"
        ? `${GMV_TIKTOK_LABEL} — envelope ${GMV_TIKTOK_ENVELOPE_KEY}`
        : entry.label,
    lastUpdated: formatDateTime(envelope.computed_at),
    dataMode: "live",
    ...workflow,
    sparkline: values,
    timeSeries,
    forecastSeries: undefined,
    previousTimeSeries: undefined,
    gaugeValue: undefined,
    partialNote:
      range === "90d" && values.length < 9
        ? "Một phần dữ liệu nguồn chưa đầy đủ cho khoảng thời gian đang chọn."
        : undefined,
  };
}

export function buildSupplementaryChartSnapshot(
  envelope: DemoAnalyticsEnvelope,
  envelopeKey: "product_funnel" | "live_performance",
): SupplementaryChartSnapshot | null {
  assertNoNetRevenueAlias(envelope);

  const entry = envelope.kpis[envelopeKey];
  if (!isAnalyticsKpiAvailable(entry) || !entry.series?.length) {
    return null;
  }

  const timeSeries = seriesToTimePoints(entry);
  const values = entry.series.map((point) => point.v);
  const latestValue = values[values.length - 1]!;
  const { delta, trend } = computeDelta(entry.series);

  return {
    envelopeKey,
    label: entry.label,
    formattedValue: formatVND(latestValue),
    delta,
    trend,
    timeSeries,
    dataSource: entry.label,
    lastUpdated: formatDateTime(envelope.computed_at),
  };
}

export function listSupplementaryCharts(
  envelope: DemoAnalyticsEnvelope | null | undefined,
): SupplementaryChartSnapshot[] {
  if (!envelope) {
    return [];
  }

  return (["product_funnel", "live_performance"] as const)
    .map((key) => buildSupplementaryChartSnapshot(envelope, key))
    .filter((chart): chart is SupplementaryChartSnapshot => chart !== null);
}
