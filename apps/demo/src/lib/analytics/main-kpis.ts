export type MetricKey =
  | "sps"
  | "net-revenue"
  | "roas"
  | "inventory-turnover"
  | "fulfillment-accuracy-rate"
  | "csat";

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
  "sps",
  "net-revenue",
  "roas",
  "inventory-turnover",
  "fulfillment-accuracy-rate",
  "csat",
] as const;

export const DEFAULT_METRIC_KEY: MetricKey = "net-revenue";
export const DEFAULT_ANALYTICS_RANGE: AnalyticsRange = "30d";

export const ANALYTICS_RANGE_LABELS: Record<AnalyticsRange, string> = {
  "7d": "7 ngày",
  "30d": "30 ngày",
  "90d": "90 ngày",
};

export const MAIN_KPI_DEFINITIONS: Record<MetricKey, MainKpiDefinition> = {
  sps: {
    metricKey: "sps",
    category: "Trạng thái shop",
    name: "SPS",
    description: "Điểm hiệu suất shop trên TikTok Shop.",
    icon: "◎",
    available: false,
    chartKind: "health-bar",
    unavailableReason: {
      dataSource: "TikTok Shop Account health contract",
      activationRequirement:
        "Cần xác minh và kết nối hợp đồng sức khỏe tài khoản TikTok Shop chính thức trước khi hiển thị SPS.",
    },
  },
  "net-revenue": {
    metricKey: "net-revenue",
    category: "Doanh thu",
    name: "Doanh thu thuần",
    description: "Doanh thu sau khấu trừ hoàn tiền và hủy đơn.",
    icon: "₫",
    available: true,
    chartKind: "forecast-line",
  },
  roas: {
    metricKey: "roas",
    category: "Quảng cáo",
    name: "ROAS",
    description: "Lợi nhuận quảng cáo trên chi tiêu quảng cáo.",
    icon: "◎",
    available: false,
    chartKind: "forecast-line",
    unavailableReason: {
      dataSource: "TikTok Promotion API",
      activationRequirement:
        "Cần kết nối luồng dữ liệu TikTok Promotion API trước khi hiển thị ROAS.",
    },
  },
  "inventory-turnover": {
    metricKey: "inventory-turnover",
    category: "Tồn kho",
    name: "Vòng quay tồn kho",
    description: "Tốc độ bán hết và thay thế hàng tồn.",
    icon: "↻",
    available: true,
    chartKind: "trend-line",
  },
  "fulfillment-accuracy-rate": {
    metricKey: "fulfillment-accuracy-rate",
    category: "Vận hành",
    name: "Tỷ lệ giao đúng",
    description: "Tỷ lệ đơn giao đúng hàng và đúng hạn.",
    icon: "✓",
    available: true,
    chartKind: "gauge",
  },
  csat: {
    metricKey: "csat",
    category: "Chăm sóc khách hàng",
    name: "CSAT",
    description: "Mức hài lòng của người mua sau mua hàng.",
    icon: "★",
    available: false,
    chartKind: "gauge",
    unavailableReason: {
      dataSource: "Nguồn đánh giá/chat người mua",
      activationRequirement:
        "Cần có nguồn đánh giá hoặc chat người mua hợp lệ trước khi hiển thị CSAT.",
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

export function getSelectorMetricKeys(heroMetricKey: MetricKey): MetricKey[] {
  return MAIN_KPI_ORDER.filter((key) => key !== heroMetricKey);
}
