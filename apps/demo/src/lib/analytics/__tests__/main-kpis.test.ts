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

describe("main-kpis catalog (DUX-2: Demo Main KPI override per ADR-049)", () => {
  it("AC1 (RED): MAIN_KPI_ORDER has exactly five Demo Main KPIs in correct order", () => {
    expect(MAIN_KPI_ORDER).toHaveLength(5);
    expect(MAIN_KPI_ORDER).toEqual([
      "gmv-tiktok",
      "aov",
      "ctor",
      "live-hours",
      "cancellation-rate",
    ]);
  });

  it("AC1 (RED): DEFAULT_METRIC_KEY is gmv-tiktok (hero)", () => {
    expect(DEFAULT_METRIC_KEY).toBe("gmv-tiktok");
    expect(DEFAULT_ANALYTICS_RANGE).toBe("30d");
  });

  it("AC1 (RED): getSelectorMetricKeys returns exactly four keys (excluding hero)", () => {
    const selectorKeys = getSelectorMetricKeys("gmv-tiktok");
    expect(selectorKeys).toHaveLength(4);
    expect(selectorKeys).toEqual(["aov", "ctor", "live-hours", "cancellation-rate"]);
    expect(selectorKeys).not.toContain("gmv-tiktok");
  });

  it("AC5: each of five KPIs has available:true and is defined in MAIN_KPI_DEFINITIONS", () => {
    for (const key of MAIN_KPI_ORDER) {
      expect(isValidMetricKey(key)).toBe(true);
      expect(isAvailableMetricKey(key)).toBe(true);
      const definition = getMainKpiDefinition(key);
      expect(definition.available).toBe(true);
      expect(definition.unavailableReason).toBeUndefined();
    }
  });

  it("AC2 (RED): removed ADR-023 KPIs (SPS, ROAS, CSAT, Net Revenue, Inventory, Fulfillment) are invalid", () => {
    for (const removedKey of [
      "sps",
      "roas",
      "csat",
      "net-revenue",
      "inventory-turnover",
      "fulfillment-accuracy-rate",
    ] as const) {
      expect(isValidMetricKey(removedKey)).toBe(false);
    }
  });

  it("AC5: gmv-tiktok definition has correct Vietnamese labels", () => {
    const gmv = getMainKpiDefinition("gmv-tiktok");
    expect(gmv.name).toMatch(/GMV.*TikTok/i);
    expect(gmv.available).toBe(true);
  });

  it("AC5: aov definition has correct Vietnamese labels", () => {
    const aov = getMainKpiDefinition("aov");
    expect(aov.name).toMatch(/AOV/i);
    expect(aov.available).toBe(true);
  });

  it("AC5: ctor definition has correct Vietnamese labels (CTOR not CTR)", () => {
    const ctor = getMainKpiDefinition("ctor");
    expect(ctor.name).toMatch(/CTOR|click/i);
    expect(ctor.available).toBe(true);
  });

  it("AC5: live-hours definition has correct Vietnamese labels", () => {
    const liveHours = getMainKpiDefinition("live-hours");
    expect(liveHours.name).toMatch(/LIVE|live/i);
    expect(liveHours.available).toBe(true);
  });

  it("AC5: cancellation-rate definition has correct Vietnamese labels", () => {
    const cancelRate = getMainKpiDefinition("cancellation-rate");
    expect(cancelRate.name).toMatch(/hủy|Cancellation/i);
    expect(cancelRate.available).toBe(true);
  });
});

describe("getSelectorMetricKeys with trend-aware ordering (DUX-3: Downtrend emphasis)", () => {
  it("AC6 (RED): returns static order when no trends provided", () => {
    const selectorKeys = getSelectorMetricKeys("gmv-tiktok");
    expect(selectorKeys).toEqual(["aov", "ctor", "live-hours", "cancellation-rate"]);
  });

  it("AC6 (RED): puts negative-trend KPIs first when trends provided", () => {
    const trends = {
      aov: "positive",
      ctor: "negative",
      "live-hours": "neutral",
      "cancellation-rate": "positive",
    } as const;

    const selectorKeys = getSelectorMetricKeys("gmv-tiktok", trends);

    // ctor (negative) should appear first, then neutrals (live-hours), then positives
    expect(selectorKeys[0]).toBe("ctor");
    expect(selectorKeys).toEqual(["ctor", "live-hours", "aov", "cancellation-rate"]);
  });

  it("AC6 (RED): orders multiple negative trends first, then neutral, then positive", () => {
    const trends = {
      aov: "negative",
      ctor: "negative",
      "live-hours": "neutral",
      "cancellation-rate": "positive",
    } as const;

    const selectorKeys = getSelectorMetricKeys("gmv-tiktok", trends);

    // Both negative should be first (in their relative order from MAIN_KPI_ORDER)
    expect(selectorKeys.indexOf("aov")).toBeLessThan(selectorKeys.indexOf("live-hours"));
    expect(selectorKeys.indexOf("ctor")).toBeLessThan(selectorKeys.indexOf("live-hours"));
    expect(selectorKeys.indexOf("live-hours")).toBeLessThan(selectorKeys.indexOf("cancellation-rate"));
  });

  it("AC6 (RED): preserves relative order within same trend tier", () => {
    const trends = {
      aov: "positive",
      ctor: "positive",
      "live-hours": "positive",
      "cancellation-rate": "positive",
    } as const;

    const selectorKeys = getSelectorMetricKeys("gmv-tiktok", trends);

    // All positive, so should maintain MAIN_KPI_ORDER
    expect(selectorKeys).toEqual(["aov", "ctor", "live-hours", "cancellation-rate"]);
  });

  it("AC6 (RED): handles missing trends by treating as neutral", () => {
    const trends = {
      aov: "negative",
      // ctor missing → treated as neutral
      // live-hours missing → treated as neutral
      "cancellation-rate": "positive",
    } as const;

    const selectorKeys = getSelectorMetricKeys("gmv-tiktok", trends);

    // negative first, then neutrals (ctor, live-hours), then positive
    expect(selectorKeys[0]).toBe("aov");
    expect(selectorKeys[selectorKeys.length - 1]).toBe("cancellation-rate");
  });
});
