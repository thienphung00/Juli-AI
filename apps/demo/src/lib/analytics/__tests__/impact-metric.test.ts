import { describe, expect, it } from "vitest";

import { buildImpactMetricSnapshot } from "../envelope-mapper";
import { createMockDemoAnalyticsEnvelope } from "./fixtures";

/**
 * Impact metric snapshot (ADR-055 items 15–17, issue #771).
 *
 * The impact block reads the tied Main KPI's REAL current value and trend
 * from the serving envelope. It never fabricates a value and never renders
 * a projected magnitude.
 */
describe("buildImpactMetricSnapshot", () => {
  it("returns the real latest CTOR value and rising trend from the envelope", () => {
    const envelope = createMockDemoAnalyticsEnvelope();

    const snapshot = buildImpactMetricSnapshot(envelope, "ctor");

    expect(snapshot).not.toBeNull();
    // Latest real point in the fixture series is 3.8 (pre-divided ratio KPI).
    expect(snapshot!.formattedValue).toBe("3,8%");
    // 3.2 → 3.8 is a +19% move.
    expect(snapshot!.delta).toBe("▲ 19%");
    expect(snapshot!.trend).toBe("positive");
    expect(snapshot!.sentiment).toBe("positive");
    expect(snapshot!.metricName).toBe("CTOR (click→đơn)");
  });

  it("returns the real latest GMV value formatted as VND", () => {
    const envelope = createMockDemoAnalyticsEnvelope();

    const snapshot = buildImpactMetricSnapshot(envelope, "gmv-tiktok");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.formattedValue).toContain("485.000.000");
    expect(snapshot!.trend).toBe("positive");
  });

  it("treats a falling cancellation rate as a positive sentiment", () => {
    // Fixture series: 2.5 → 1.8 — the rate is falling, which is good.
    const envelope = createMockDemoAnalyticsEnvelope();

    const snapshot = buildImpactMetricSnapshot(envelope, "cancellation-rate");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.trend).toBe("negative");
    expect(snapshot!.sentiment).toBe("positive");
    expect(snapshot!.delta).toBe("▼ 28%");
  });

  it("treats a rising cancellation rate as a negative sentiment", () => {
    const envelope = createMockDemoAnalyticsEnvelope({
      kpis: {
        cancellation_rate: {
          availability: "available",
          label: "Tỷ lệ hủy đơn",
          series: [
            { t: "2026-07-01", v: 1.8 },
            { t: "2026-07-20", v: 2.5 },
          ],
        },
      },
    });

    const snapshot = buildImpactMetricSnapshot(envelope, "cancellation-rate");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.trend).toBe("positive");
    expect(snapshot!.sentiment).toBe("negative");
  });

  it("returns null when there is no envelope — never a fabricated value", () => {
    expect(buildImpactMetricSnapshot(null, "ctor")).toBeNull();
    expect(buildImpactMetricSnapshot(undefined, "ctor")).toBeNull();
  });

  it("returns null when the envelope has no value for the metric", () => {
    const envelope = createMockDemoAnalyticsEnvelope({
      kpis: {
        ctor: {
          availability: "unavailable",
          label: "CTOR (click→đơn)",
        },
      },
    });

    expect(buildImpactMetricSnapshot(envelope, "ctor")).toBeNull();
    // A metric missing from the envelope entirely is also honest-unavailable.
    expect(buildImpactMetricSnapshot(envelope, "aov")).toBeNull();
  });

  it("keeps a real value with an honest em-dash trend when the series has one point", () => {
    const envelope = createMockDemoAnalyticsEnvelope({
      kpis: {
        ctor: {
          availability: "available",
          label: "CTOR (click→đơn)",
          series: [{ t: "2026-07-20", v: 3.8 }],
        },
      },
    });

    const snapshot = buildImpactMetricSnapshot(envelope, "ctor");

    expect(snapshot).not.toBeNull();
    expect(snapshot!.formattedValue).toBe("3,8%");
    expect(snapshot!.delta).toBe("—");
    expect(snapshot!.trend).toBe("neutral");
    expect(snapshot!.sentiment).toBe("neutral");
  });
});
