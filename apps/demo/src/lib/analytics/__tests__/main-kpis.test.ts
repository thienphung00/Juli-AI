import { describe, expect, it } from "vitest";

import {
  DEFAULT_ANALYTICS_RANGE,
  DEFAULT_METRIC_KEY,
  MAIN_KPI_ORDER,
  getMainKpiDefinition,
  getSelectorMetricKeys,
  isAvailableMetricKey,
  isValidMetricKey,
} from "../main-kpis";

describe("main-kpis catalog", () => {
  it("AC1: defines six Main KPI slots with GMV hero and 30 days as defaults (Phase 2.10-A supersedes Phase 2.6 net-revenue default)", () => {
    expect(MAIN_KPI_ORDER).toHaveLength(6);
    expect(DEFAULT_METRIC_KEY).toBe("gmv-tiktok");
    expect(DEFAULT_ANALYTICS_RANGE).toBe("30d");
    expect(MAIN_KPI_ORDER).toContain("gmv-tiktok");
    expect(MAIN_KPI_ORDER).not.toContain("net-revenue");
  });

  it("AC3: keeps SPS, ROAS, and CSAT visible but unavailable", () => {
    for (const key of ["sps", "roas", "csat"] as const) {
      const definition = getMainKpiDefinition(key);

      expect(definition.available).toBe(false);
      expect(definition.unavailableReason?.dataSource).toBeTruthy();
      expect(isValidMetricKey(key)).toBe(true);
      expect(isAvailableMetricKey(key)).toBe(false);
    }
  });

  it("AC4: marks Net Revenue unavailable; GMV static default; inventory/fulfillment envelope-gated", () => {
    const netRevenue = getMainKpiDefinition("net-revenue");
    expect(netRevenue.available).toBe(false);
    expect(netRevenue.unavailableReason?.activationRequirement).toMatch(
      /refund|hủy|cancellation/i,
    );
    expect(isAvailableMetricKey("net-revenue")).toBe(false);

    const gmv = getMainKpiDefinition("gmv-tiktok");
    expect(gmv.available).toBe(true);
    expect(gmv.name).toMatch(/GMV/i);
    expect(gmv.name).not.toBe("Doanh thu thuần");
    expect(isAvailableMetricKey("gmv-tiktok")).toBe(true);

    for (const key of [
      "inventory-turnover",
      "fulfillment-accuracy-rate",
    ] as const) {
      expect(getMainKpiDefinition(key).available).toBe(false);
      expect(isAvailableMetricKey(key)).toBe(false);
      expect(getMainKpiDefinition(key).unavailableReason).toBeTruthy();
    }
  });

  it("AC4: returns five selector keys excluding the hero metric", () => {
    expect(getSelectorMetricKeys("gmv-tiktok")).toHaveLength(5);
    expect(getSelectorMetricKeys("gmv-tiktok")).not.toContain("gmv-tiktok");
    expect(getSelectorMetricKeys("inventory-turnover")).toContain("gmv-tiktok");
  });

  it("release journey: main_kpi_hero_label_is_gmv_or_unavailable_not_net_revenue_alias", () => {
    const gmv = getMainKpiDefinition("gmv-tiktok");
    const netRevenue = getMainKpiDefinition("net-revenue");

    expect(gmv.name).toMatch(/GMV/i);
    expect(gmv.name).not.toBe("Doanh thu thuần");
    expect(netRevenue.available).toBe(false);
    expect(DEFAULT_METRIC_KEY).toBe("gmv-tiktok");
  });

  it("release journey: ads_roas_cac_ctr_marked_unavailable", () => {
    expect(getMainKpiDefinition("roas").available).toBe(false);
    expect(getMainKpiDefinition("roas").unavailableReason?.dataSource).toBeTruthy();
  });

  it("release journey: shop_status_sps_ahr_vp_marked_unavailable", () => {
    expect(getMainKpiDefinition("sps").available).toBe(false);
    expect(getMainKpiDefinition("sps").unavailableReason?.dataSource).toBeTruthy();
  });
});
