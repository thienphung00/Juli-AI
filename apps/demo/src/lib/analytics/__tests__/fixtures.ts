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
  inventory_turnover: {
    availability: "available",
    label: "Inventory turnover",
    series: [
      { t: "2026-07-01", v: 5.4 },
      { t: "2026-07-20", v: 3.1 },
    ],
  },
  fulfillment_accuracy_rate: {
    availability: "available",
    label: "Fulfillment accuracy rate",
    series: [
      { t: "2026-07-01", v: 98.6 },
      { t: "2026-07-20", v: 95.2 },
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
