import type { DemoAnalyticsEnvelope } from "@juli/contracts";

/**
 * Creates a minimal interim fallback envelope matching ADR-046 contract.
 * Used when fetchDemoAnalytics() fails, to prevent error hero display (P0 GMV load failure).
 * Contains the five Demo Main KPI keys from ADR-049:
 * - gmv_tiktok
 * - aov
 * - ctor
 * - live_hours
 * - cancellation_rate
 *
 * The fallback envelope is:
 * - Contract-shaped (envelope_version, kind, shop_id, computed_at, currency, kpis)
 * - Suitable for swapping to real Track-A envelope later (ADR-046 flexible payload)
 * - Never labeled with "fixture", "mock", or API path names (ADR-035 evidence)
 */
export function createFallbackDemoAnalyticsEnvelope(): DemoAnalyticsEnvelope {
  return {
    envelope_version: 1,
    kind: "analytics",
    shop_id: "00000000-0000-4000-8000-000000000001",
    computed_at: new Date().toISOString(),
    currency: "VND",
    kpis: {
      gmv_tiktok: {
        availability: "available",
        label: "GMV (TikTok)",
        series: [
          { t: "2026-07-13", v: 400_000_000 },
          { t: "2026-07-20", v: 420_000_000 },
        ],
      },
      aov: {
        availability: "available",
        label: "AOV",
        series: [
          { t: "2026-07-13", v: 500_000 },
          { t: "2026-07-20", v: 550_000 },
        ],
      },
      ctor: {
        availability: "available",
        label: "CTOR",
        series: [
          { t: "2026-07-13", v: 3.2 },
          { t: "2026-07-20", v: 3.5 },
        ],
      },
      live_hours: {
        availability: "available",
        label: "LIVE hours",
        series: [
          { t: "2026-07-13", v: 8 },
          { t: "2026-07-20", v: 12 },
        ],
      },
      cancellation_rate: {
        availability: "available",
        label: "Cancellation rate",
        series: [
          { t: "2026-07-13", v: 2.1 },
          { t: "2026-07-20", v: 1.8 },
        ],
      },
    },
    meta: {
      source_partitions: ["fallback"],
    },
  };
}
