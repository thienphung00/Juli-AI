export type PersonaId = "new" | "leakage" | "growth";

export type WorkflowId = "new_seller" | "leakage" | "growth";

export type TaskSeverity = "high" | "medium" | "low" | "info";

export type OrderStatus =
  | "processing"
  | "shipping"
  | "delivered"
  | "returned"
  | "cancelled";

export type ReturnStatus = "pending_review" | "approved" | "rejected";

export type AffiliateEventType =
  | "commission_earned"
  | "order_cancelled"
  | "suspicious_cancellation";

export type AdCampaignStatus = "active" | "paused" | "ended";

export interface SellerProfile {
  id: PersonaId;
  shop_id: string;
  shop_name: string;
  shop_age_days: number;
  order_count_30d: number;
  return_rate_30d: number;
  ad_spend_30d_vnd: number;
  gmv_30d_vnd: number;
}

export interface MockTask {
  id: string;
  workflow: WorkflowId;
  type: string;
  severity: TaskSeverity;
  title: string;
  body: string;
  cta_label: string;
  estimated_impact_vnd: number | null;
  evidence_refs: string[];
  copy_source: "mock";
}

export interface MockOrder {
  id: string;
  shop_id: string;
  buyer_id: string;
  product_title: string;
  quantity: number;
  total_vnd: number;
  status: OrderStatus;
  created_at: string;
}

export interface MockReturn {
  id: string;
  order_id: string;
  buyer_id: string;
  product_title: string;
  reason: string;
  refund_vnd: number;
  status: ReturnStatus;
  created_at: string;
}

export interface MockAffiliateEvent {
  id: string;
  affiliate_id: string;
  order_id: string;
  event_type: AffiliateEventType;
  cancellation_reason: string | null;
  gmv_vnd: number;
  created_at: string;
}

export interface MockAdCampaign {
  id: string;
  campaign_name: string;
  spend_vnd: number;
  roas: number;
  cpc_vnd: number;
  conversions: number;
  status: AdCampaignStatus;
  period_days: number;
}

export interface SellerPersona {
  profile: SellerProfile;
  orders: MockOrder[];
  returns: MockReturn[];
  affiliate_events: MockAffiliateEvent[];
  ad_campaigns: MockAdCampaign[];
  tasks: MockTask[];
}
