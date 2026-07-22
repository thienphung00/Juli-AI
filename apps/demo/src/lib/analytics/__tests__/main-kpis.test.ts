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
  it("AC1: defines exactly six Main KPIs with Net Revenue and 30 days as defaults", () => {
    expect(MAIN_KPI_ORDER).toHaveLength(6);
    expect(DEFAULT_METRIC_KEY).toBe("net-revenue");
    expect(DEFAULT_ANALYTICS_RANGE).toBe("30d");
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

  it("AC2: marks Net Revenue, Inventory Turnover, and Fulfillment Accuracy as available", () => {
    for (const key of [
      "net-revenue",
      "inventory-turnover",
      "fulfillment-accuracy-rate",
    ] as const) {
      expect(getMainKpiDefinition(key).available).toBe(true);
      expect(isAvailableMetricKey(key)).toBe(true);
    }
  });

  it("AC4: returns five selector keys excluding the hero metric", () => {
    expect(getSelectorMetricKeys("net-revenue")).toHaveLength(5);
    expect(getSelectorMetricKeys("net-revenue")).not.toContain("net-revenue");
    expect(getSelectorMetricKeys("inventory-turnover")).toContain("net-revenue");
  });
});
