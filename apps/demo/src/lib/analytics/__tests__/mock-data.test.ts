import { describe, expect, it } from "vitest";

import { getKpiSnapshot, getPreviewSnapshot } from "../mock-data";

describe("analytics mock-data", () => {
  it("AC2: returns documented mock values for available KPIs at 30 days", () => {
    const netRevenue = getKpiSnapshot("net-revenue", "30d");
    const inventory = getKpiSnapshot("inventory-turnover", "30d");
    const fulfillment = getKpiSnapshot("fulfillment-accuracy-rate", "30d");

    expect(netRevenue?.formattedValue).toContain("485");
    expect(netRevenue?.delta).toBe("▲ 15%");
    expect(netRevenue?.dataMode).toBe("fixture");
    expect(netRevenue?.timeSeries.length).toBeGreaterThan(0);

    expect(inventory?.formattedValue).toContain("3,1");
    expect(inventory?.delta).toBe("▼ 43%");
    expect(inventory?.forecastSeries?.length).toBeGreaterThan(0);

    expect(fulfillment?.formattedValue).toContain("95,2%");
    expect(fulfillment?.gaugeValue).toBe(95.2);
  });

  it("AC3: never returns fixture snapshots for unavailable KPIs", () => {
    expect(getKpiSnapshot("sps", "30d")).toBeNull();
    expect(getKpiSnapshot("roas", "30d")).toBeNull();
    expect(getKpiSnapshot("csat", "30d")).toBeNull();
    expect(getPreviewSnapshot("roas", "30d")).toBeNull();
  });

  it("AC5: updates available preview values transactionally per range", () => {
    const preview7d = getPreviewSnapshot("net-revenue", "7d");
    const preview30d = getPreviewSnapshot("net-revenue", "30d");

    expect(preview7d?.formattedValue).not.toBe(preview30d?.formattedValue);
    expect(preview7d?.delta).toBe("▲ 8%");
    expect(preview30d?.delta).toBe("▲ 15%");
  });

  it("AC6: exposes provenance, freshness, and decision deep links for available KPIs", () => {
    const snapshot = getKpiSnapshot("net-revenue", "30d");

    expect(snapshot?.dataSource).toContain("fixture");
    expect(snapshot?.lastUpdated).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    expect(snapshot?.workflowId).toBe("optimize_product_2");
    expect(snapshot?.decisionLabel).toBeTruthy();
  });

  it("AC6: supports partial data annotation without inventing unavailable KPI data", () => {
    const partial = getKpiSnapshot("net-revenue", "30d", { partial: true });

    expect(partial?.partialNote).toContain("Một phần dữ liệu");
    expect(getKpiSnapshot("sps", "30d", { partial: true })).toBeNull();
  });
});
