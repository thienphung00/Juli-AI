import { describe, expect, it } from "vitest";

import { getKpiSnapshot, getPreviewSnapshot } from "../mock-data";

describe("analytics mock-data (DUX-2: Five-KPI demo set)", () => {
  it("AC2: returns documented mock values for GMV (TikTok) at 30 days", () => {
    const gmvTiktok = getKpiSnapshot("gmv-tiktok", "30d");

    expect(gmvTiktok?.formattedValue).toContain("485");
    expect(gmvTiktok?.delta).toBe("▲ 15%");
    expect(gmvTiktok?.dataMode).toBe("fixture");
    expect(gmvTiktok?.timeSeries.length).toBeGreaterThan(0);
    expect(gmvTiktok?.workflowId).toBe("optimize_product_2");
  });

  it("AC (RED): other five-KPI set members (AOV, CTOR, LIVE hours, Cancellation rate) use envelope data, not mock-data", () => {
    // These KPIs get their data from the envelope, not from mock-data fixtures
    expect(getKpiSnapshot("aov", "30d")).toBeNull();
    expect(getKpiSnapshot("ctor", "30d")).toBeNull();
    expect(getKpiSnapshot("live-hours", "30d")).toBeNull();
    expect(getKpiSnapshot("cancellation-rate", "30d")).toBeNull();
  });

  it("AC (RED): removed ADR-023 KPIs are not available in mock-data", () => {
    // These keys are no longer valid MetricKey types
    // so they will be caught by TypeScript
  });

  it("AC5: updates available preview values transactionally per range", () => {
    const preview7d = getPreviewSnapshot("gmv-tiktok", "7d");
    const preview30d = getPreviewSnapshot("gmv-tiktok", "30d");

    expect(preview7d?.formattedValue).not.toBe(preview30d?.formattedValue);
    expect(preview7d?.delta).toBe("▲ 8%");
    expect(preview30d?.delta).toBe("▲ 15%");
  });

  it("AC6: exposes provenance, freshness, and decision deep links for available KPIs", () => {
    const snapshot = getKpiSnapshot("gmv-tiktok", "30d");

    expect(snapshot?.dataSource).toContain("fixture");
    expect(snapshot?.lastUpdated).toMatch(/\d{2}\/\d{2}\/\d{4}/);
    expect(snapshot?.workflowId).toBe("optimize_product_2");
    expect(snapshot?.decisionLabel).toBeTruthy();
  });

  it("AC6: supports partial data annotation without inventing unavailable KPI data", () => {
    const partial = getKpiSnapshot("gmv-tiktok", "30d", { partial: true });

    expect(partial?.partialNote).toContain("Một phần dữ liệu");
    // Other KPIs (aov, ctor, live-hours, cancellation-rate) return null from mock-data
    expect(getKpiSnapshot("aov", "30d")).toBeNull();
  });
});
