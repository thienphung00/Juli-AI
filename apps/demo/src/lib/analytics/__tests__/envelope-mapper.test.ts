import { describe, expect, it } from "vitest";

import { createMockDemoAnalyticsEnvelope } from "./fixtures";
import {
  buildLiveKpiSnapshot,
  buildSupplementaryChartSnapshot,
  isSelectableMetricKey,
  listSupplementaryCharts,
} from "../envelope-mapper";

describe("envelope-mapper", () => {
  const envelope = createMockDemoAnalyticsEnvelope();

  it("maps gmv_tiktok to GMV (TikTok) hero snapshot without net_revenue alias", () => {
    const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
    expect(snapshot?.formattedValue).toContain("485");
    expect(snapshot?.dataMode).toBe("live");
    expect(snapshot?.dataSource).toContain("gmv_tiktok");
    expect(envelope.kpis).not.toHaveProperty("net_revenue");
  });

  it("marks inventory and fulfillment selectable only when envelope series exist", () => {
    expect(isSelectableMetricKey("inventory-turnover", envelope)).toBe(true);
    expect(isSelectableMetricKey("sps", envelope)).toBe(false);
    expect(isSelectableMetricKey("net-revenue", envelope)).toBe(false);

    const sparse = createMockDemoAnalyticsEnvelope({
      kpis: {
        gmv_tiktok: envelope.kpis.gmv_tiktok,
      },
    });
    expect(isSelectableMetricKey("inventory-turnover", sparse)).toBe(false);
  });

  it("builds product and LIVE supplementary charts when available", () => {
    expect(buildSupplementaryChartSnapshot(envelope, "product_funnel")?.label).toBe(
      "Product funnel (GMV)",
    );
    expect(listSupplementaryCharts(envelope)).toHaveLength(2);
  });
});
