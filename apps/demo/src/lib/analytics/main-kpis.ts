export type MetricKey =
  | "gmv-tiktok"
  | "aov"
  | "ctor"
  | "live-hours"
  | "cancellation-rate";

export type GoalDirection = "higher-is-better" | "lower-is-better";

export type AnalyticsRange = "7d" | "30d" | "90d";

export type ChartKind =
  | "health-bar"
  | "forecast-line"
  | "trend-line"
  | "gauge";

/**
 * Measurement type determines chart form (ADR-060).
 * - flow: sum-able quantity (GMV) → line with gradient fill
 * - average: average measure (AOV) → line, no fill
 * - rate: rate/percentage (CTOR) → line, no fill, percentage axis
 * - count: discrete per period (LIVE hours) → bars
 * - bounded-ratio: ratio with bounds (cancellation rate) → threshold band
 */
export type MeasurementType =
  | "flow"
  | "average"
  | "rate"
  | "count"
  | "bounded-ratio";

/**
 * Chart form is derived from measurement type, not hand-assigned.
 * Used internally by the resolver; not exposed in KPI definitions.
 */
export type ChartForm =
  | "filled-line"
  | "plain-line"
  | "bars"
  | "bounded-ratio";

export interface UnavailableKpiReason {
  dataSource: string;
  activationRequirement: string;
}

export interface BoundedRatioBounds {
  /** Minimum value for the bounded-ratio scale (e.g., 0% for cancellation rate). */
  min: number;
  /** Maximum value for the bounded-ratio scale (e.g., 10% for acceptable cancellation rate). */
  max: number;
}

export interface MainKpiDefinition {
  metricKey: MetricKey;
  category: string;
  name: string;
  description: string;
  icon: string;
  available: boolean;
  chartKind: ChartKind;
  goalDirection: GoalDirection;
  measurementType: MeasurementType;
  /** Bounds for bounded-ratio measurements, predetermined from metric definition. Only present for bounded-ratio KPIs. */
  boundedRatioBounds?: BoundedRatioBounds;
  unavailableReason?: UnavailableKpiReason;
}

export const MAIN_KPI_ORDER: readonly MetricKey[] = [
  "gmv-tiktok",
  "aov",
  "ctor",
  "live-hours",
  "cancellation-rate",
] as const;

/**
 * The Main KPIs a workflow's decision can be tied to (ADR-055 item 15).
 *
 * LIVE hours is deliberately absent: it is tied to no workflow, and
 * retrofitting one onto it to make the set look complete is barred.
 */
export const IMPACT_METRIC_KEYS = [
  "gmv-tiktok",
  "aov",
  "ctor",
  "cancellation-rate",
] as const;

export type ImpactMetricKey = (typeof IMPACT_METRIC_KEYS)[number];

export function isImpactMetricKey(key: string): key is ImpactMetricKey {
  return (IMPACT_METRIC_KEYS as readonly string[]).includes(key);
}

/**
 * Deep link to a Main KPI on the Analytics screen. The single place the
 * metric route is built, so a tied KPI and its link can never drift apart.
 */
export function buildAnalyticsMetricHref(metricKey: MetricKey): string {
  return `/analytics/${metricKey}`;
}

export const DEFAULT_METRIC_KEY: MetricKey = "gmv-tiktok";
export const DEFAULT_ANALYTICS_RANGE: AnalyticsRange = "30d";

export const ANALYTICS_RANGE_LABELS: Record<AnalyticsRange, string> = {
  "7d": "7 ngày",
  "30d": "30 ngày",
  "90d": "90 ngày",
};

export const MAIN_KPI_DEFINITIONS: Record<MetricKey, MainKpiDefinition> = {
  "gmv-tiktok": {
    metricKey: "gmv-tiktok",
    category: "Doanh thu",
    name: "GMV (TikTok)",
    description: "Tổng giá trị đơn hàng trên TikTok Shop trước hoàn tiền và hủy đơn.",
    icon: "₫",
    available: true,
    chartKind: "forecast-line",
    goalDirection: "higher-is-better",
    measurementType: "flow",
  },
  aov: {
    metricKey: "aov",
    category: "Doanh thu",
    name: "AOV",
    description: "Giá trị trung bình một đơn hàng.",
    icon: "₫",
    available: true,
    chartKind: "forecast-line",
    goalDirection: "higher-is-better",
    measurementType: "average",
  },
  ctor: {
    metricKey: "ctor",
    category: "Quản lý sản phẩm",
    name: "CTOR (click→đơn)",
    description: "Tỷ lệ chuyển đổi từ click thành đơn hàng.",
    icon: "◎",
    available: true,
    chartKind: "trend-line",
    goalDirection: "higher-is-better",
    measurementType: "rate",
  },
  "live-hours": {
    metricKey: "live-hours",
    category: "LIVE Shopping",
    name: "LIVE hours",
    description: "Tổng số giờ phát sóng LIVE trong khoảng thời gian.",
    icon: "◉",
    available: true,
    chartKind: "forecast-line",
    goalDirection: "higher-is-better",
    measurementType: "count",
  },
  "cancellation-rate": {
    metricKey: "cancellation-rate",
    category: "Quản lý đơn hàng",
    name: "Tỷ lệ hủy đơn",
    description: "Tỷ lệ phần trăm đơn hàng bị hủy.",
    icon: "✗",
    available: true,
    chartKind: "gauge",
    goalDirection: "lower-is-better",
    measurementType: "bounded-ratio",
    boundedRatioBounds: {
      min: 0,
      max: 10,
    },
  },
};

export function isValidMetricKey(key: string): key is MetricKey {
  return Object.hasOwn(MAIN_KPI_DEFINITIONS, key);
}

export function isAvailableMetricKey(key: string): key is MetricKey {
  return isValidMetricKey(key) && MAIN_KPI_DEFINITIONS[key].available;
}

export function getMainKpiDefinition(metricKey: MetricKey): MainKpiDefinition {
  return MAIN_KPI_DEFINITIONS[metricKey];
}

/**
 * Get selector metric keys, optionally reordered to put negative/downtrend KPIs first.
 * If no trends provided, returns static MAIN_KPI_ORDER (excluding hero).
 * If trends provided, sorts by negative/downtrend first for visual emphasis.
 * ADR-049 Decision 1: puts negative KPIs before neutral/positive.
 */
export function getSelectorMetricKeys(
  heroMetricKey: MetricKey,
  trends?: Partial<Record<MetricKey, "negative" | "neutral" | "positive" | "warning">>,
): MetricKey[] {
  const candidates = MAIN_KPI_ORDER.filter((key) => key !== heroMetricKey);

  if (!trends) {
    return candidates;
  }

  // Partition candidates by trend priority: negative/warning first, then neutral, then positive
  const negatives: MetricKey[] = [];
  const neutrals: MetricKey[] = [];
  const positives: MetricKey[] = [];

  for (const key of candidates) {
    const trend = trends[key] ?? "neutral";
    if (trend === "negative" || trend === "warning") {
      negatives.push(key);
    } else if (trend === "neutral") {
      neutrals.push(key);
    } else {
      positives.push(key);
    }
  }

  return [...negatives, ...neutrals, ...positives];
}

/**
 * Resolve chart form from measurement type (ADR-060).
 * This is the single decision point for chart appearance.
 * No other module decides what a KPI looks like.
 *
 * | Measurement type | Form | Example |
 * |---|---|---|
 * | flow | filled-line | GMV (sum-able quantity) |
 * | average | plain-line | AOV (average value) |
 * | rate | plain-line | CTOR (percentage) |
 * | count | bars | LIVE hours (discrete per period) |
 * | bounded-ratio | bounded-ratio | Cancellation rate (threshold band) |
 */
export function getChartFormFromMeasurementType(
  measurementType: MeasurementType
): ChartForm {
  switch (measurementType) {
    case "flow":
      return "filled-line";
    case "average":
      return "plain-line";
    case "rate":
      return "plain-line";
    case "count":
      return "bars";
    case "bounded-ratio":
      return "bounded-ratio";
  }
}
