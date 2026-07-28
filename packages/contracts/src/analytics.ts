/** Analytics KPI envelope types for public Demo read API (#525 / #531). */

export type AnalyticsKpiAvailability = "available" | "unavailable";

export interface AnalyticsKpiSeriesPoint {
  t: string;
  v: number;
}

export interface AnalyticsKpiEntry {
  availability: AnalyticsKpiAvailability;
  label: string;
  series?: readonly AnalyticsKpiSeriesPoint[];
}

/** Known envelope KPI keys — GMV uses `gmv_tiktok`, never `net_revenue`. */
export type AnalyticsEnvelopeKpiKey =
  | "gmv_tiktok"
  | "product_funnel"
  | "live_performance"
  | "inventory_turnover"
  | "fulfillment_accuracy_rate"
  | "sps"
  | "roas"
  | "csat";

export interface DemoAnalyticsEnvelopeMeta {
  source_partitions?: readonly string[];
  notes?: readonly string[];
}

export interface DemoAnalyticsEnvelope {
  envelope_version: number;
  kind: "analytics";
  shop_id: string;
  computed_at: string;
  currency: string;
  kpis: Partial<Record<AnalyticsEnvelopeKpiKey, AnalyticsKpiEntry>> &
    Record<string, AnalyticsKpiEntry | undefined>;
  meta?: DemoAnalyticsEnvelopeMeta;
}

export const GMV_TIKTOK_ENVELOPE_KEY = "gmv_tiktok" as const;
export const GMV_TIKTOK_LABEL = "GMV (TikTok)" as const;

/** Guard against silent GMV → Net Revenue aliasing in envelope payloads. */
export function assertNoNetRevenueAlias(envelope: DemoAnalyticsEnvelope): void {
  if ("net_revenue" in envelope.kpis || "net-revenue" in envelope.kpis) {
    throw new Error(
      "Envelope must not alias GMV as net_revenue — use gmv_tiktok with label GMV (TikTok)",
    );
  }
}

export function isAnalyticsKpiAvailable(
  entry: AnalyticsKpiEntry | undefined,
): entry is AnalyticsKpiEntry & { availability: "available" } {
  return entry?.availability === "available";
}
