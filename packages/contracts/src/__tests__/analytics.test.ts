import { describe, expect, it } from "vitest";

import {
  GMV_TIKTOK_ENVELOPE_KEY,
  GMV_TIKTOK_LABEL,
  assertNoNetRevenueAlias,
  isAnalyticsKpiAvailable,
  type DemoAnalyticsEnvelope,
} from "../analytics";

const sampleEnvelope: DemoAnalyticsEnvelope = {
  envelope_version: 1,
  kind: "analytics",
  shop_id: "00000000-0000-4000-8000-000000000001",
  computed_at: "2026-07-20T08:30:00+07:00",
  currency: "VND",
  kpis: {
    [GMV_TIKTOK_ENVELOPE_KEY]: {
      availability: "available",
      label: GMV_TIKTOK_LABEL,
      series: [{ t: "2026-07-20", v: 485_000_000 }],
    },
    product_funnel: {
      availability: "available",
      label: "Product funnel (GMV)",
      series: [{ t: "2026-07-20", v: 120_000_000 }],
    },
    live_performance: {
      availability: "unavailable",
      label: "LIVE performance (GMV)",
    },
  },
  meta: { source_partitions: ["A-36", "A-34"] },
};

describe("Demo analytics envelope contracts", () => {
  it("uses gmv_tiktok key with GMV (TikTok) label — not net_revenue", () => {
    const gmv = sampleEnvelope.kpis.gmv_tiktok;
    expect(gmv?.label).toBe("GMV (TikTok)");
    expect(sampleEnvelope.kpis).not.toHaveProperty("net_revenue");
    expect(sampleEnvelope.kpis).not.toHaveProperty("net-revenue");
  });

  it("assertNoNetRevenueAlias rejects net_revenue alias keys", () => {
    expect(() =>
      assertNoNetRevenueAlias({
        ...sampleEnvelope,
        kpis: {
          ...sampleEnvelope.kpis,
          net_revenue: {
            availability: "available",
            label: "Doanh thu thuần",
            series: [{ t: "2026-07-20", v: 1 }],
          },
        },
      }),
    ).toThrow(/net_revenue/);
  });

  it("isAnalyticsKpiAvailable distinguishes available vs unavailable entries", () => {
    expect(isAnalyticsKpiAvailable(sampleEnvelope.kpis.gmv_tiktok)).toBe(true);
    expect(isAnalyticsKpiAvailable(sampleEnvelope.kpis.live_performance)).toBe(
      false,
    );
    expect(isAnalyticsKpiAvailable(undefined)).toBe(false);
  });
});
