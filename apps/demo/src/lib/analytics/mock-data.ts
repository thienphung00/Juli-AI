import type { ChartTrend } from "@juli/ui";
import { formatDateTime, formatNumber, formatVND } from "@juli/utils";

import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../workflows/optimize-product/review";
import { PROCESS_ORDER_WORKFLOW_KEY } from "../workflows/process-order/review";
import { REPLENISH_INVENTORY_WORKFLOW_KEY } from "../workflows/replenish-inventory/review";
import type { AnalyticsRange, MetricKey } from "./main-kpis";

export interface KpiTimePoint {
  label: string;
  value: number;
}

export interface KpiSnapshot {
  formattedValue: string;
  delta: string;
  trend: ChartTrend;
  signal: string;
  dataSource: string;
  lastUpdated: string;
  dataMode: "fixture";
  partialNote?: string;
  workflowId?: string;
  decisionLabel?: string;
  sparkline: readonly number[];
  timeSeries: readonly KpiTimePoint[];
  forecastSeries?: readonly KpiTimePoint[];
  previousTimeSeries?: readonly KpiTimePoint[];
  gaugeValue?: number;
}

const FIXTURE_UPDATED_AT = "2026-07-20T08:30:00+07:00";

interface RangeBundle {
  netRevenue: number;
  netRevenueDelta: string;
  inventoryTurnover: number;
  inventoryDelta: string;
  fulfillmentAccuracy: number;
  fulfillmentDelta: string;
}

const RANGE_VALUES: Record<AnalyticsRange, RangeBundle> = {
  "7d": {
    netRevenue: 118_000_000,
    netRevenueDelta: "▲ 8%",
    inventoryTurnover: 4.2,
    inventoryDelta: "▼ 12%",
    fulfillmentAccuracy: 96.8,
    fulfillmentDelta: "▼ 1.2 điểm %",
  },
  "30d": {
    netRevenue: 485_000_000,
    netRevenueDelta: "▲ 15%",
    inventoryTurnover: 3.1,
    inventoryDelta: "▼ 43%",
    fulfillmentAccuracy: 95.2,
    fulfillmentDelta: "▼ 3.4 điểm %",
  },
  "90d": {
    netRevenue: 1_420_000_000,
    netRevenueDelta: "▲ 22%",
    inventoryTurnover: 2.8,
    inventoryDelta: "▼ 48%",
    fulfillmentAccuracy: 94.5,
    fulfillmentDelta: "▼ 4.1 điểm %",
  },
};

function buildTimeSeries(
  range: AnalyticsRange,
  base: number,
  drift: number,
): KpiTimePoint[] {
  const points =
    range === "7d" ? 7 : range === "30d" ? 6 : 9;

  return Array.from({ length: points }, (_, index) => ({
    label: `T${index + 1}`,
    value: Math.round(base + drift * index),
  }));
}

function buildForecastSeries(
  timeSeries: readonly KpiTimePoint[],
  uplift: number,
): KpiTimePoint[] {
  return timeSeries.map((point, index) => ({
    label: point.label,
    value: Math.round(point.value * (1 + uplift / 100) + index * 2),
  }));
}

function buildPreviousSeries(
  timeSeries: readonly KpiTimePoint[],
  ratio: number,
): KpiTimePoint[] {
  return timeSeries.map((point) => ({
    label: point.label,
    value: Math.round(point.value * ratio),
  }));
}

function netRevenueSnapshot(range: AnalyticsRange): KpiSnapshot {
  const bundle = RANGE_VALUES[range];
  const timeSeries = buildTimeSeries(range, 72, 8);
  const forecastSeries = buildForecastSeries(timeSeries, 6);

  return {
    formattedValue: formatVND(bundle.netRevenue),
    delta: bundle.netRevenueDelta,
    trend: "positive",
    signal:
      "Doanh thu thuần tăng mạnh → cơ hội tăng trưởng → xem xét mở rộng sản phẩm chủ lực",
    dataSource: "TikTok Shop Order API (fixture)",
    lastUpdated: formatDateTime(FIXTURE_UPDATED_AT),
    dataMode: "fixture",
    workflowId: OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    decisionLabel: "Xem đề xuất tối ưu sản phẩm",
    sparkline: timeSeries.map((point) => point.value),
    timeSeries,
    forecastSeries,
    previousTimeSeries: buildPreviousSeries(timeSeries, 0.87),
  };
}

function inventoryTurnoverSnapshot(range: AnalyticsRange): KpiSnapshot {
  const bundle = RANGE_VALUES[range];
  const timeSeries = buildTimeSeries(range, 52, -3).map((point) => ({
    ...point,
    value: Number((point.value / 10).toFixed(1)),
  }));
  const forecastSeries = buildForecastSeries(timeSeries, -4).map((point) => ({
    ...point,
    value: Number((point.value / 10).toFixed(1)),
  }));

  return {
    formattedValue: `${formatNumber(bundle.inventoryTurnover)}x`,
    delta: bundle.inventoryDelta,
    trend: "negative",
    signal:
      "Vòng quay tồn kho giảm → rủi ro vốn bị kẹt → cân nhắc bổ sung hoặc thanh lý tồn",
    dataSource: "TikTok Shop Inventory API (fixture)",
    lastUpdated: formatDateTime(FIXTURE_UPDATED_AT),
    dataMode: "fixture",
    workflowId: REPLENISH_INVENTORY_WORKFLOW_KEY,
    decisionLabel: "Xem đề xuất bổ sung tồn kho",
    sparkline: timeSeries.map((point) => point.value * 10),
    timeSeries,
    forecastSeries,
    previousTimeSeries: buildPreviousSeries(timeSeries, 1.35).map((point) => ({
      ...point,
      value: Number((point.value).toFixed(1)),
    })),
  };
}

function fulfillmentAccuracySnapshot(range: AnalyticsRange): KpiSnapshot {
  const bundle = RANGE_VALUES[range];
  const gaugeValue = bundle.fulfillmentAccuracy;

  return {
    formattedValue: `${formatNumber(gaugeValue)}%`,
    delta: bundle.fulfillmentDelta,
    trend: "negative",
    signal:
      "Tỷ lệ giao đúng giảm → rủi ro lỗi tăng → kiểm tra quy trình xử lý đơn",
    dataSource: "TikTok Shop Fulfillment API (fixture)",
    lastUpdated: formatDateTime(FIXTURE_UPDATED_AT),
    dataMode: "fixture",
    workflowId: PROCESS_ORDER_WORKFLOW_KEY,
    decisionLabel: "Xem đề xuất xử lý đơn",
    sparkline: [98.6, 97.4, 96.9, 96.2, 95.8, 95.2].slice(0, range === "7d" ? 5 : 6),
    timeSeries: buildTimeSeries(range, 986, -4).map((point) => ({
      label: point.label,
      value: Number((point.value / 10).toFixed(1)),
    })),
    gaugeValue,
    previousTimeSeries: buildPreviousSeries(
      buildTimeSeries(range, 986, -4),
      1.03,
    ).map((point) => ({
      label: point.label,
      value: Number((point.value / 10).toFixed(1)),
    })),
  };
}

export function getKpiSnapshot(
  metricKey: MetricKey,
  range: AnalyticsRange,
  options?: { partial?: boolean },
): KpiSnapshot | null {
  let snapshot: KpiSnapshot | null = null;

  switch (metricKey) {
    case "net-revenue":
      snapshot = netRevenueSnapshot(range);
      break;
    case "inventory-turnover":
      snapshot = inventoryTurnoverSnapshot(range);
      break;
    case "fulfillment-accuracy-rate":
      snapshot = fulfillmentAccuracySnapshot(range);
      break;
    default:
      return null;
  }

  if (options?.partial) {
    return {
      ...snapshot,
      partialNote: "Một phần dữ liệu nguồn chưa đầy đủ cho khoảng thời gian đang chọn.",
    };
  }

  return snapshot;
}

export function getPreviewSnapshot(
  metricKey: MetricKey,
  range: AnalyticsRange,
): Pick<KpiSnapshot, "formattedValue" | "delta" | "trend" | "sparkline"> | null {
  const snapshot = getKpiSnapshot(metricKey, range);

  if (!snapshot) {
    return null;
  }

  return {
    formattedValue: snapshot.formattedValue,
    delta: snapshot.delta,
    trend: snapshot.trend,
    sparkline: snapshot.sparkline,
  };
}
