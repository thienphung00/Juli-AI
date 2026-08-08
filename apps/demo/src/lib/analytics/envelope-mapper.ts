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
import {
  getMainKpiDefinition,
  type AnalyticsRange,
  type GoalDirection,
  type ImpactMetricKey,
  type MetricKey,
} from "./main-kpis";
import type { KpiSnapshot, KpiTimePoint } from "./mock-data";

const METRIC_TO_ENVELOPE_KEY: Record<MetricKey, string> = {
  "gmv-tiktok": GMV_TIKTOK_ENVELOPE_KEY,
  aov: "aov",
  ctor: "ctor",
  "live-hours": "live_hours",
  "cancellation-rate": "cancellation_rate",
};

/** Seller-facing source labels (no API vocabulary) — ADR-049 Decision 3 */
const METRIC_TO_DATA_SOURCE: Record<MetricKey, string> = {
  "gmv-tiktok": "TikTok Shop",
  aov: "TikTok Shop",
  ctor: "TikTok Shop",
  "live-hours": "TikTok Shop",
  "cancellation-rate": "TikTok Shop",
};

/**
 * Calculate relative freshness from computed_at timestamp.
 * Returns "Cập nhật N phút/giờ trước" format with live indicator.
 * ADR-049 Decision 3 requires relative freshness + live indicator.
 */
export function getRelativeFreshness(computedAtIso: string): string {
  const computedAt = new Date(computedAtIso);
  const now = new Date();
  const diffMs = now.getTime() - computedAt.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  let relative: string;
  if (diffMinutes < 1) {
    relative = "Cập nhật vừa xong";
  } else if (diffMinutes < 60) {
    relative = `Cập nhật ${diffMinutes} phút trước`;
  } else if (diffHours < 24) {
    relative = `Cập nhật ${diffHours} giờ trước`;
  } else {
    relative = `Cập nhật ${diffDays} ngày trước`;
  }

  // Add live indicator
  return `${relative} · Live`;
}

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

/**
 * Resolve semantic tone as a function of delta sign and goal direction.
 * This is the single source of tone derivation (ADR-060).
 *
 * The tone represents whether the move is good or bad for the seller,
 * considering both the direction of movement and the KPI's goal direction.
 *
 * @param pct - The percentage change; positive means rising, negative means falling
 * @param goalDirection - Whether higher or lower is the desired direction
 * @returns The semantic tone: "positive" for good direction, "negative" for bad, "neutral" for zero
 */
export function resolveToneFromDeltaAndGoal(
  pct: number,
  goalDirection: GoalDirection,
): ChartTrend {
  // Zero change is always neutral, regardless of goal direction
  if (pct === 0) {
    return "neutral";
  }

  // For higher-is-better KPIs: positive delta → positive tone, negative delta → negative tone
  if (goalDirection === "higher-is-better") {
    return pct > 0 ? "positive" : "negative";
  }

  // For lower-is-better KPIs: positive delta (increase) → negative tone, negative delta (decrease) → positive tone
  return pct > 0 ? "negative" : "positive";
}

/**
 * Compute the delta (change) between first and last value in a series.
 * Returns both raw trend (movement direction) and goal-aware tone (if goalDirection provided).
 *
 * @param series - The time series data points
 * @param goalDirection - Goal direction for tone resolution; if provided, tone reflects goal-awareness
 * @returns Delta string, raw trend (movement direction), and goal-aware tone
 */
function computeDelta(
  series: readonly { v: number }[],
  goalDirection?: GoalDirection,
): {
  delta: string;
  rawTrend: ChartTrend;
  tone: ChartTrend;
} {
  if (series.length < 2) {
    return { delta: "—", rawTrend: "neutral", tone: "neutral" };
  }

  const first = series[0]!.v;
  const last = series[series.length - 1]!.v;

  if (first === 0) {
    return { delta: "—", rawTrend: "neutral", tone: "neutral" };
  }

  const pct = Math.round(((last - first) / Math.abs(first)) * 100);
  // Arrow always reflects raw movement: up for positive pct, down for negative pct
  const arrow = pct > 0 ? "▲" : pct < 0 ? "▼" : "—";

  // Raw trend is always based on movement direction only
  const rawTrend: ChartTrend = pct > 0 ? "positive" : pct < 0 ? "negative" : "neutral";

  // Tone is resolved using goal direction if provided; otherwise same as raw trend
  const tone: ChartTrend = goalDirection
    ? resolveToneFromDeltaAndGoal(pct, goalDirection)
    : rawTrend;

  return {
    delta: `${arrow} ${Math.abs(pct)}%`,
    rawTrend,
    tone,
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
  const def = getMainKpiDefinition(metricKey);
  const { delta, tone } = computeDelta(entry.series, def.goalDirection);
  const workflow = metricWorkflow(metricKey);

  return {
    formattedValue: formatKpiValue(metricKey, latestValue, envelope.currency),
    delta,
    trend: tone,
    signal: metricSignal(metricKey, tone),
    dataSource: METRIC_TO_DATA_SOURCE[metricKey],
    lastUpdated: getRelativeFreshness(envelope.computed_at),
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

/**
 * A tied Main KPI as the decision plan review's impact block reads it
 * (ADR-055 items 15–17, issue #771).
 *
 * Every field is derived from the serving envelope or from the KPI's own
 * authored definition. There is no projection field, and there is nothing
 * here to fabricate when the envelope is silent — the builder returns `null`
 * instead, and the block renders an honest unavailable state.
 */
export interface ImpactMetricSnapshot {
  /** The tied KPI. */
  metricKey: ImpactMetricKey;
  /** Seller-facing KPI name, from the Main KPI definition. */
  metricName: string;
  /** Real latest value from the envelope series, formatted for the seller. */
  formattedValue: string;
  /** Real period-over-period move, e.g. "▲ 19%" — "—" when unknowable. */
  delta: string;
  /** Direction of the move, as charted. */
  trend: ChartTrend;
  /**
   * Whether that move is good for the seller. Identical to `trend` except on
   * inverted KPIs (cancellation rate), where falling is the good direction.
   */
  sentiment: ChartTrend;
}

/**
 * Read the tied Main KPI's real current value and trend.
 *
 * Returns `null` — never a placeholder, never a computed guess — when there is
 * no envelope, when the KPI is unavailable, or when it carries no series.
 * Ratio KPIs (CTOR, cancellation rate) arrive pre-divided and are rendered as
 * stored; correcting that belongs to the CDP track, not here.
 *
 * The `sentiment` field is the goal-aware tone (whether the move is good for the
 * seller), computed by the unified resolver (resolveToneFromDeltaAndGoal). The
 * `trend` field is always raw movement (up = positive, down = negative).
 * Both are computed once in computeDelta and read directly (no duplication).
 */
export function buildImpactMetricSnapshot(
  envelope: DemoAnalyticsEnvelope | null | undefined,
  metricKey: ImpactMetricKey,
): ImpactMetricSnapshot | null {
  if (!envelope) {
    return null;
  }

  const entry = getEnvelopeKpiEntry(envelope, metricKey);
  if (!isAnalyticsKpiAvailable(entry) || !entry.series?.length) {
    return null;
  }

  const values = entry.series.map((point) => point.v);
  const latestValue = values[values.length - 1]!;
  const def = getMainKpiDefinition(metricKey);
  const { delta, rawTrend: trend, tone: sentiment } = computeDelta(
    entry.series,
    def.goalDirection,
  );

  return {
    metricKey,
    metricName: def.name,
    formattedValue: formatKpiValue(metricKey, latestValue, envelope.currency),
    delta,
    trend,
    sentiment,
  };
}

/**
 * Goal directions for supplementary charts.
 * These are not Main KPIs but need explicit goal direction to go through the unified resolver.
 * ADR-060 Consequence: all series require goal direction to prevent inversion trap.
 */
const SUPPLEMENTARY_CHART_GOAL_DIRECTIONS: Record<
  "product_funnel" | "live_performance",
  GoalDirection
> = {
  product_funnel: "higher-is-better", // Funnel conversion rising is good
  live_performance: "higher-is-better", // LIVE performance GMV rising is good
};

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
  const goalDirection = SUPPLEMENTARY_CHART_GOAL_DIRECTIONS[envelopeKey];
  const { delta, tone } = computeDelta(entry.series, goalDirection);

  return {
    envelopeKey,
    label: entry.label,
    formattedValue: formatVND(latestValue),
    delta,
    trend: tone,
    timeSeries,
    dataSource: "TikTok Shop",
    lastUpdated: getRelativeFreshness(envelope.computed_at),
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
