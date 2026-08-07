export type MetricKey =
  | "gmv-tiktok"
  | "aov"
  | "ctor"
  | "live-hours"
  | "cancellation-rate";

export type AnalyticsRange = "7d" | "30d" | "90d";

export type ChartKind =
  | "health-bar"
  | "forecast-line"
  | "trend-line"
  | "gauge";

export interface UnavailableKpiReason {
  dataSource: string;
  activationRequirement: string;
}

export interface MainKpiDefinition {
  metricKey: MetricKey;
  category: string;
  name: string;
  description: string;
  icon: string;
  available: boolean;
  chartKind: ChartKind;
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
  },
  aov: {
    metricKey: "aov",
    category: "Doanh thu",
    name: "AOV",
    description: "Giá trị trung bình một đơn hàng.",
    icon: "₫",
    available: true,
    chartKind: "forecast-line",
  },
  ctor: {
    metricKey: "ctor",
    category: "Quản lý sản phẩm",
    name: "CTOR (click→đơn)",
    description: "Tỷ lệ chuyển đổi từ click thành đơn hàng.",
    icon: "◎",
    available: true,
    chartKind: "trend-line",
  },
  "live-hours": {
    metricKey: "live-hours",
    category: "LIVE Shopping",
    name: "LIVE hours",
    description: "Tổng số giờ phát sóng LIVE trong khoảng thời gian.",
    icon: "◉",
    available: true,
    chartKind: "forecast-line",
  },
  "cancellation-rate": {
    metricKey: "cancellation-rate",
    category: "Quản lý đơn hàng",
    name: "Tỷ lệ hủy đơn",
    description: "Tỷ lệ phần trăm đơn hàng bị hủy.",
    icon: "✗",
    available: true,
    chartKind: "gauge",
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
