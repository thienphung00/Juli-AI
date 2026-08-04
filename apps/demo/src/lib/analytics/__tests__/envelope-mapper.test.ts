import { describe, expect, it } from "vitest";

import { createMockDemoAnalyticsEnvelope } from "./fixtures";
import {
  buildLiveKpiSnapshot,
  buildSupplementaryChartSnapshot,
  isSelectableMetricKey,
  listSupplementaryCharts,
} from "../envelope-mapper";

describe("envelope-mapper (DUX-2: Five-KPI envelope mapping)", () => {
  const envelope = createMockDemoAnalyticsEnvelope();

  it("AC4 (RED): maps gmv_tiktok to GMV (TikTok) hero snapshot without net_revenue alias", () => {
    const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
    expect(snapshot?.formattedValue).toContain("485");
    expect(snapshot?.dataMode).toBe("live");
    expect(snapshot?.dataSource).toContain("gmv_tiktok");
    expect(envelope.kpis).not.toHaveProperty("net_revenue");
  });

  it("AC4 (RED): METRIC_TO_ENVELOPE_KEY contains only five Demo Main KPIs", () => {
    // This test validates that removed keys are not in the mapping
    expect(isSelectableMetricKey("gmv-tiktok", envelope)).toBe(true);
    expect(isSelectableMetricKey("aov", envelope)).toBe(true);
    expect(isSelectableMetricKey("ctor", envelope)).toBe(true);
    expect(isSelectableMetricKey("live-hours", envelope)).toBe(true);
    expect(isSelectableMetricKey("cancellation-rate", envelope)).toBe(true);

    // Removed keys should not be selectable
    expect(isSelectableMetricKey("sps", envelope)).toBe(false);
    expect(isSelectableMetricKey("roas", envelope)).toBe(false);
    expect(isSelectableMetricKey("csat", envelope)).toBe(false);
    expect(isSelectableMetricKey("net-revenue", envelope)).toBe(false);
    expect(isSelectableMetricKey("inventory-turnover", envelope)).toBe(false);
    expect(isSelectableMetricKey("fulfillment-accuracy-rate", envelope)).toBe(false);
  });

  it("AC5 (RED): formats KPI values in correct units (currency, percentage, hours)", () => {
    // GMV should format as VND currency
    const gmvSnapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
    expect(gmvSnapshot?.formattedValue).toMatch(/₫/); // VND currency symbol

    // AOV should also format as VND currency (derived from GMV / orders)
    const aovSnapshot = buildLiveKpiSnapshot(envelope, "aov", "30d");
    expect(aovSnapshot?.formattedValue).toMatch(/₫/);

    // CTOR should format as percentage
    const ctorSnapshot = buildLiveKpiSnapshot(envelope, "ctor", "30d");
    expect(ctorSnapshot?.formattedValue).toMatch(/%/);

    // Cancellation rate should format as percentage
    const cancelRateSnapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
    expect(cancelRateSnapshot?.formattedValue).toMatch(/%/);
  });

  it("builds product and LIVE supplementary charts when available", () => {
    expect(buildSupplementaryChartSnapshot(envelope, "product_funnel")?.label).toBe(
      "Product funnel (GMV)",
    );
    expect(listSupplementaryCharts(envelope)).toHaveLength(2);
  });
});
