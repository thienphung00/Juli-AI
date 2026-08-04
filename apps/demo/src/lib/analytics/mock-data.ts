import type { ChartTrend } from "@juli/ui";
import { formatDateTime, formatNumber, formatVND } from "@juli/utils";

import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../workflows/optimize-product/review";
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
  dataMode: "fixture" | "live";
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
  gmvTiktok: number;
  gmvTiktokDelta: string;
}

const RANGE_VALUES: Record<AnalyticsRange, RangeBundle> = {
  "7d": {
    gmvTiktok: 118_000_000,
    gmvTiktokDelta: "▲ 8%",
  },
  "30d": {
    gmvTiktok: 485_000_000,
    gmvTiktokDelta: "▲ 15%",
  },
  "90d": {
    gmvTiktok: 1_420_000_000,
    gmvTiktokDelta: "▲ 22%",
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

function gmvTiktokSnapshot(range: AnalyticsRange): KpiSnapshot {
  const bundle = RANGE_VALUES[range];
  const timeSeries = buildTimeSeries(range, 72, 8);
  const forecastSeries = buildForecastSeries(timeSeries, 6);

  return {
    formattedValue: formatVND(bundle.gmvTiktok),
    delta: bundle.gmvTiktokDelta,
    trend: "positive",
    signal:
      "GMV TikTok tăng mạnh → cơ hội tăng trưởng → xem xét mở rộng sản phẩm chủ lực",
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


export function getKpiSnapshot(
  metricKey: MetricKey,
  range: AnalyticsRange,
  options?: { partial?: boolean },
): KpiSnapshot | null {
  let snapshot: KpiSnapshot | null = null;

  switch (metricKey) {
    case "gmv-tiktok":
      snapshot = gmvTiktokSnapshot(range);
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
