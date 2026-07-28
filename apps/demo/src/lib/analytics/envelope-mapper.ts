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
import { PROCESS_ORDER_WORKFLOW_KEY } from "../workflows/process-order/review";
import { REPLENISH_INVENTORY_WORKFLOW_KEY } from "../workflows/replenish-inventory/review";
import type { AnalyticsRange, MetricKey } from "./main-kpis";
import type { KpiSnapshot, KpiTimePoint } from "./mock-data";

const METRIC_TO_ENVELOPE_KEY: Partial<Record<MetricKey, string>> = {
  "gmv-tiktok": GMV_TIKTOK_ENVELOPE_KEY,
  "inventory-turnover": "inventory_turnover",
  "fulfillment-accuracy-rate": "fulfillment_accuracy_rate",
  sps: "sps",
  roas: "roas",
  csat: "csat",
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
      return formatVND(value);
    case "inventory-turnover":
      return `${formatNumber(value)}x`;
    case "fulfillment-accuracy-rate":
      return `${formatNumber(value)}%`;
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
    case "inventory-turnover":
      return trend === "negative"
        ? "Vòng quay tồn kho giảm → rủi ro vốn bị kẹt → cân nhắc bổ sung hoặc thanh lý tồn"
        : "Vòng quay tồn kho ổn định → theo dõi tồn kho chủ lực";
    case "fulfillment-accuracy-rate":
      return trend === "negative"
        ? "Tỷ lệ giao đúng giảm → rủi ro lỗi tăng → kiểm tra quy trình xử lý đơn"
        : "Tỷ lệ giao đúng ổn định → duy trì quy trình vận hành";
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
    case "inventory-turnover":
      return {
        workflowId: REPLENISH_INVENTORY_WORKFLOW_KEY,
        decisionLabel: "Xem đề xuất bổ sung tồn kho",
      };
    case "fulfillment-accuracy-rate":
      return {
        workflowId: PROCESS_ORDER_WORKFLOW_KEY,
        decisionLabel: "Xem đề xuất xử lý đơn",
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
  if (metricKey === "net-revenue") {
    return false;
  }

  const entry = getEnvelopeKpiEntry(envelope, metricKey);
  return isAnalyticsKpiAvailable(entry) && Boolean(entry.series?.length);
}

export function isSelectableMetricKey(
  key: string,
  envelope?: DemoAnalyticsEnvelope | null,
): key is MetricKey {
  if (!Object.hasOwn(METRIC_TO_ENVELOPE_KEY, key as MetricKey) && key !== "net-revenue") {
    // Static unavailable KPIs in MAIN_KPI_ORDER (sps, roas, csat)
    return false;
  }

  if (key === "gmv-tiktok" || key === "inventory-turnover" || key === "fulfillment-accuracy-rate") {
    return isMetricLiveAvailable(envelope, key as MetricKey);
  }

  return false;
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
    gaugeValue:
      metricKey === "fulfillment-accuracy-rate" ? latestValue : undefined,
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
