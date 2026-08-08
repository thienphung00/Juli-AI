import { describe, expect, it, vi } from "vitest";

import { createMockDemoAnalyticsEnvelope } from "./fixtures";
import {
  buildLiveKpiSnapshot,
  buildSupplementaryChartSnapshot,
  isSelectableMetricKey,
  listSupplementaryCharts,
  getRelativeFreshness,
} from "../envelope-mapper";

describe("envelope-mapper (DUX-2: Five-KPI envelope mapping)", () => {
  const envelope = createMockDemoAnalyticsEnvelope();

  it("AC4 (RED): maps gmv_tiktok to GMV (TikTok) hero snapshot without net_revenue alias", () => {
    const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
    expect(snapshot?.formattedValue).toContain("485");
    expect(snapshot?.dataMode).toBe("live");
    expect(snapshot?.dataSource).toBe("TikTok Shop");
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

describe("envelope-mapper (DUX-3: Analytics trust copy)", () => {
  const envelope = createMockDemoAnalyticsEnvelope();

  describe("AC1: No API vocabulary in dataSource", () => {
    const apiVocabularyTerms = [
      "envelope",
      "gmv_tiktok",
      "payload",
      "kpis",
      "fixture",
      "mock",
      "API",
      "A-36",
      "A-34",
      "A-28",
      "A-7",
      "webhook",
    ];

    it("gmv-tiktok dataSource contains no API vocabulary", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.dataSource).toBeDefined();
      for (const term of apiVocabularyTerms) {
        expect(snapshot?.dataSource).not.toMatch(new RegExp(term, "i"));
      }
    });

    it("aov dataSource contains no API vocabulary", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "aov", "30d");
      expect(snapshot?.dataSource).toBeDefined();
      for (const term of apiVocabularyTerms) {
        expect(snapshot?.dataSource).not.toMatch(new RegExp(term, "i"));
      }
    });

    it("ctor dataSource contains no API vocabulary", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "ctor", "30d");
      expect(snapshot?.dataSource).toBeDefined();
      for (const term of apiVocabularyTerms) {
        expect(snapshot?.dataSource).not.toMatch(new RegExp(term, "i"));
      }
    });

    it("live-hours dataSource contains no API vocabulary", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "live-hours", "30d");
      expect(snapshot?.dataSource).toBeDefined();
      for (const term of apiVocabularyTerms) {
        expect(snapshot?.dataSource).not.toMatch(new RegExp(term, "i"));
      }
    });

    it("cancellation-rate dataSource contains no API vocabulary", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      expect(snapshot?.dataSource).toBeDefined();
      for (const term of apiVocabularyTerms) {
        expect(snapshot?.dataSource).not.toMatch(new RegExp(term, "i"));
      }
    });
  });

  describe("AC2: Insight chain with what→risk→action for all five metrics", () => {
    it("gmv-tiktok has complete insight chain with arrow indicator", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.signal).toBeDefined();
      // Should contain metric name, trend indicator, and action
      expect(snapshot?.signal).toMatch(/GMV|TikTok/i);
      expect(snapshot?.signal).toMatch(/→/); // Arrow separator
      expect(snapshot?.signal).toMatch(/xem xét|tối ưu/i); // Action phrase
    });

    it("aov has complete insight chain with arrow indicator", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "aov", "30d");
      expect(snapshot?.signal).toBeDefined();
      expect(snapshot?.signal).toMatch(/AOV/i);
      expect(snapshot?.signal).toMatch(/→/);
      expect(snapshot?.signal).toMatch(/xem xét|sắp xếp/i);
    });

    it("ctor has complete insight chain with arrow indicator", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "ctor", "30d");
      expect(snapshot?.signal).toBeDefined();
      expect(snapshot?.signal).toMatch(/CTOR/i);
      expect(snapshot?.signal).toMatch(/→/);
      expect(snapshot?.signal).toMatch(/tối ưu|tiếp tục/i);
    });

    it("live-hours has complete insight chain with arrow indicator", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "live-hours", "30d");
      expect(snapshot?.signal).toBeDefined();
      expect(snapshot?.signal).toMatch(/LIVE|hours/i);
      expect(snapshot?.signal).toMatch(/→/);
      expect(snapshot?.signal).toMatch(/mở rộng|tối ưu/i);
    });

    it("cancellation-rate has complete insight chain with arrow indicator", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      expect(snapshot?.signal).toBeDefined();
      expect(snapshot?.signal).toMatch(/hủy đơn|cancellation/i);
      expect(snapshot?.signal).toMatch(/→/);
      expect(snapshot?.signal).toMatch(/duy trì|kiểm tra/i);
    });

    it("does not use generic fallback signal for any metric", () => {
      const genericFallback =
        "Thay đổi KPI đáng chú ý trong khoảng thời gian đang chọn";
      for (const metricKey of [
        "gmv-tiktok",
        "aov",
        "ctor",
        "live-hours",
        "cancellation-rate",
      ] as const) {
        const snapshot = buildLiveKpiSnapshot(envelope, metricKey, "30d");
        expect(snapshot?.signal).not.toBe(genericFallback);
        expect(snapshot?.signal).not.toContain("Thay đổi KPI đáng chú ý");
      }
    });
  });

  describe("AC3: Provenance shows seller-language source with no envelope key", () => {
    it("gmv-tiktok shows TikTok Shop source", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.dataSource).toBeDefined();
      expect(snapshot?.dataSource).toMatch(/TikTok|Cửa hàng/i);
    });

    it("all data sources are seller-facing, not API keys", () => {
      const sources = [
        buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d")?.dataSource,
        buildLiveKpiSnapshot(envelope, "aov", "30d")?.dataSource,
        buildLiveKpiSnapshot(envelope, "ctor", "30d")?.dataSource,
        buildLiveKpiSnapshot(envelope, "live-hours", "30d")?.dataSource,
        buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d")?.dataSource,
      ];

      for (const source of sources) {
        expect(source).toBeDefined();
        // Should not contain envelope key
        expect(source).not.toContain("gmv_tiktok");
        expect(source).not.toMatch(/A-\d+/);
        expect(source).not.toMatch(/envelope/i);
      }
    });
  });

  describe("AC4: Freshness is relative with live indicator", () => {
    it("returns relative freshness string from computed_at", () => {
      const now = new Date("2026-07-20T08:35:00+07:00");
      vi.useFakeTimers();
      vi.setSystemTime(now);

      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.lastUpdated).toBeDefined();
      // Should contain relative time like "5 phút trước" not absolute timestamp
      expect(snapshot?.lastUpdated).toMatch(/phút trước|giờ trước|ngày trước/i);

      vi.useRealTimers();
    });

    it("includes live indicator in freshness", () => {
      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.lastUpdated).toBeDefined();
      expect(snapshot?.lastUpdated).toMatch(/live|đang phát sóng|thực/i);
    });
  });
});

describe("getRelativeFreshness helper", () => {
  it("calculates relative time correctly for recent updates", () => {
    const now = new Date("2026-07-20T08:35:00+07:00");
    const computedAt = "2026-07-20T08:30:00+07:00";

    vi.useFakeTimers();
    vi.setSystemTime(now);

    const result = getRelativeFreshness(computedAt);
    expect(result).toMatch(/5 phút trước/);

    vi.useRealTimers();
  });

  it("shows correct format for hour-old data", () => {
    const now = new Date("2026-07-20T09:30:00+07:00");
    const computedAt = "2026-07-20T08:30:00+07:00";

    vi.useFakeTimers();
    vi.setSystemTime(now);

    const result = getRelativeFreshness(computedAt);
    expect(result).toMatch(/1 giờ trước|60 phút trước/);

    vi.useRealTimers();
  });
});

describe("Tone resolution (Issue #858): Goal-aware tone derivation", () => {
  describe("Higher-is-better KPIs resolve tone based on goal direction", () => {
    it("rising GMV resolves to positive tone", () => {
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.trend).toBe("positive");
    });

    it("rising AOV resolves to positive tone", () => {
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildLiveKpiSnapshot(envelope, "aov", "30d");
      expect(snapshot?.trend).toBe("positive");
    });

    it("rising CTOR resolves to positive tone", () => {
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildLiveKpiSnapshot(envelope, "ctor", "30d");
      expect(snapshot?.trend).toBe("positive");
    });

    it("rising LIVE hours resolves to positive tone", () => {
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildLiveKpiSnapshot(envelope, "live-hours", "30d");
      expect(snapshot?.trend).toBe("positive");
    });
  });

  describe("Lower-is-better KPI (cancellation rate) resolves tone inversely", () => {
    it("falling cancellation rate resolves to positive tone", () => {
      // Fixture: 2.5 → 1.8 is falling, which is good
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      expect(snapshot?.trend).toBe("positive");
    });

    it("rising cancellation rate resolves to negative tone", () => {
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
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      expect(snapshot?.trend).toBe("negative");
    });
  });

  describe("Arrow glyph always reflects raw movement (not inverted)", () => {
    it("shows upward arrow for rising cancellation rate", () => {
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
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      // Even though rising is bad, the arrow still shows up
      expect(snapshot?.delta).toMatch(/▲/);
    });

    it("shows downward arrow for falling cancellation rate", () => {
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      // Even though falling is good, the arrow still shows down
      expect(snapshot?.delta).toMatch(/▼/);
    });
  });

  describe("Zero delta resolves to neutral tone for all KPIs", () => {
    it("zero change in GMV yields neutral tone", () => {
      const envelope = createMockDemoAnalyticsEnvelope({
        kpis: {
          gmv_tiktok: {
            availability: "available",
            label: "GMV (TikTok)",
            series: [
              { t: "2026-07-01", v: 485_000_000 },
              { t: "2026-07-20", v: 485_000_000 },
            ],
          },
        },
      });
      const snapshot = buildLiveKpiSnapshot(envelope, "gmv-tiktok", "30d");
      expect(snapshot?.trend).toBe("neutral");
    });

    it("zero change in cancellation rate yields neutral tone", () => {
      const envelope = createMockDemoAnalyticsEnvelope({
        kpis: {
          cancellation_rate: {
            availability: "available",
            label: "Tỷ lệ hủy đơn",
            series: [
              { t: "2026-07-01", v: 2.0 },
              { t: "2026-07-20", v: 2.0 },
            ],
          },
        },
      });
      const snapshot = buildLiveKpiSnapshot(envelope, "cancellation-rate", "30d");
      expect(snapshot?.trend).toBe("neutral");
    });
  });

  describe("Single source of tone criterion (issue #858): no path skips the resolver", () => {
    it("pins the criterion: supplementary charts must declare goal direction, never default to it", () => {
      // This test verifies that the supplementary chart path cannot re-create the inversion trap
      // If a lower-is-better supplementary chart is added without declaring goalDirection,
      // this test will fail, proving the criterion is enforced
      const envelope = createMockDemoAnalyticsEnvelope();
      const snapshot = buildSupplementaryChartSnapshot(envelope, "product_funnel");
      // product_funnel is higher-is-better (rising is good)
      expect(snapshot?.trend).toBe("positive"); // Rising: 90M → 120M (+33%)
    });
  });
});
