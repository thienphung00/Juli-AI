import type { PersonaId } from "@/lib/mock-data/seller-personas/schemas";

/** ADR-013 Appendix A — exactly six validated workflows. */
export const VALIDATED_WORKFLOW_IDS = [
  "npl",
  "minimize_violations",
  "budget_optimization",
  "product_scaling",
  "refund_spike_detection",
  "stockout_prevention",
] as const;

export type ValidatedWorkflowId = (typeof VALIDATED_WORKFLOW_IDS)[number];

export type ShopProfileType = "NEW_SHOP" | "MID_LARGE_SHOP";

export type ProbationStatus = "active" | "graduated" | "not_applicable";

export type HealthDataSource = "mock" | "seller_center_proxy" | "unavailable";

export type AdCampaignStatus = "active" | "paused" | "ended";

export type ReturnAuthorizationStatus = "pending" | "approved" | "rejected";

export interface ShopMetadata {
  shop_id: string;
  shop_name: string;
  profile: ShopProfileType;
  probation_status: ProbationStatus;
  graduation_date: string | null;
  shop_age_days: number;
}

export interface ViolationRecord {
  violation_id: string;
  category: string;
  count: number;
  severity: "high" | "medium" | "low";
}

export interface ProbationData {
  probation_start_date: string;
  probation_end_date: string;
  sps_current: number;
  sps_threshold: number;
  ahr_current: number;
  ahr_threshold: number;
  violations: ViolationRecord[];
}

export interface AdCampaignPerformance {
  campaign_id: string;
  campaign_name: string;
  status: AdCampaignStatus;
  spend_vnd: number;
  impressions: number;
  clicks: number;
  ctr: number;
  conversions: number;
  revenue_vnd: number;
  roas: number;
  cpc_vnd: number;
  cpm_vnd: number;
  period_days: number;
}

export interface ProductPerformance {
  product_id: string;
  sku_id: string;
  product_name: string;
  category: string;
  units_sold_24h: number;
  units_sold_7d: number;
  units_sold_30d: number;
  revenue_vnd_24h: number;
  revenue_vnd_7d: number;
  revenue_vnd_30d: number;
  price_vnd: number;
  margin_pct: number;
  sell_through_rate: number;
}

export interface InventoryRecord {
  product_id: string;
  sku_id: string;
  inventory_level: number;
  sales_velocity_units_per_day: number;
  reorder_lead_time_days: number;
}

export interface RefundReasonSummary {
  reason: string;
  count_30d: number;
  share_pct: number;
}

export interface PendingReturnAuthorization {
  return_id: string;
  order_id: string;
  product_name: string;
  status: ReturnAuthorizationStatus;
  refund_vnd: number;
}

export interface ReturnsRefundsData {
  refund_count_7d: number;
  refund_count_30d: number;
  refund_rate_7d: number;
  refund_rate_30d: number;
  baseline_refund_rate_30d: number;
  top_refund_reasons: RefundReasonSummary[];
  pending_return_authorizations: PendingReturnAuthorization[];
}

/**
 * Stable P1.8 input envelope for the operations pipeline.
 * P2 swaps loaders; schema shape remains stable per ADR-013.
 */
export interface UnifiedOperationalDataModel {
  shop_metadata: ShopMetadata;
  probation: ProbationData | null;
  ad_campaigns: AdCampaignPerformance[];
  products: ProductPerformance[];
  inventory: InventoryRecord[];
  returns: ReturnsRefundsData;
  health_data_source: HealthDataSource;
  collected_at: string;
  demo_persona_id: PersonaId | null;
}

export type OperationalProfileId = ShopProfileType;
