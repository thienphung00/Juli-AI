import {
  GMV_TIKTOK_ENVELOPE_KEY,
  GMV_TIKTOK_LABEL,
  type DemoAnalyticsEnvelope,
} from "@juli/contracts";

const DEFAULT_KPIS: DemoAnalyticsEnvelope["kpis"] = {
  [GMV_TIKTOK_ENVELOPE_KEY]: {
    availability: "available",
    label: GMV_TIKTOK_LABEL,
    series: [
      { t: "2026-07-01", v: 420_000_000 },
      { t: "2026-07-20", v: 485_000_000 },
    ],
  },
  aov: {
    availability: "available",
    label: "AOV",
    series: [
      { t: "2026-07-01", v: 450_000 },
      { t: "2026-07-20", v: 500_000 },
    ],
  },
  ctor: {
    availability: "available",
    label: "CTOR (click→đơn)",
    series: [
      { t: "2026-07-01", v: 3.2 },
      { t: "2026-07-20", v: 3.8 },
    ],
  },
  live_hours: {
    availability: "available",
    label: "LIVE hours",
    series: [
      { t: "2026-07-01", v: 6 },
      { t: "2026-07-20", v: 10 },
    ],
  },
  cancellation_rate: {
    availability: "available",
    label: "Tỷ lệ hủy đơn",
    series: [
      { t: "2026-07-01", v: 2.5 },
      { t: "2026-07-20", v: 1.8 },
    ],
  },
  product_funnel: {
    availability: "available",
    label: "Product funnel (GMV)",
    series: [
      { t: "2026-07-01", v: 90_000_000 },
      { t: "2026-07-20", v: 120_000_000 },
    ],
  },
  live_performance: {
    availability: "available",
    label: "LIVE performance (GMV)",
    series: [
      { t: "2026-07-01", v: 12_000_000 },
      { t: "2026-07-20", v: 18_000_000 },
    ],
  },
};

export function createMockDemoAnalyticsEnvelope(
  overrides: Partial<DemoAnalyticsEnvelope> = {},
): DemoAnalyticsEnvelope {
  const { kpis: overrideKpis, meta: overrideMeta, ...rest } = overrides;

  return {
    envelope_version: 1,
    kind: "analytics",
    shop_id: "00000000-0000-4000-8000-000000000001",
    computed_at: "2026-07-20T08:30:00+07:00",
    currency: "VND",
    ...rest,
    kpis: overrideKpis ?? DEFAULT_KPIS,
    meta: overrideMeta ?? { source_partitions: ["A-36", "A-34", "A-28"] },
  };
}

export function createMockFetchResponse(
  envelope: DemoAnalyticsEnvelope = createMockDemoAnalyticsEnvelope(),
) {
  return async () =>
    ({
      ok: true,
      json: async () => envelope,
    }) as Response;
}

// Re-export from production code for test usage
export { createFallbackDemoAnalyticsEnvelope } from "../fallback-envelope";

// Helper for creating mock KpiSnapshot for component tests
import type { KpiSnapshot } from "../mock-data";

export function createMockSnapshot(
  overrides: Partial<KpiSnapshot> = {}
): KpiSnapshot {
  return {
    formattedValue: "500 triệu",
    delta: "▲ 15%",
    trend: "positive",
    // Matches delta/trend above: a rise on a higher-is-better KPI (#887).
    movement: { direction: "up", assessment: "favorable" },
    signal: "Tín hiệu tích cực",
    dataSource: "Mock fixture",
    lastUpdated: "20/07/2026",
    dataMode: "fixture",
    sparkline: [12, 14, 13, 16, 18],
    timeSeries: [
      { label: "T1", value: 100 },
      { label: "T2", value: 120 },
      { label: "T3", value: 135 },
    ],
    forecastSeries: [
      { label: "T1", value: 100 },
      { label: "T2", value: 125 },
      { label: "T3", value: 140 },
    ],
    previousTimeSeries: [
      { label: "T1", value: 90 },
      { label: "T2", value: 105 },
      { label: "T3", value: 115 },
    ],
    boundedRatio: undefined,
    ...overrides,
  };
}
