export type ProductDraftStatus = "in_progress" | "ready_for_export" | "blocked";

export type ProductDraftSourceType =
  | "manual_form"
  | "url_stub"
  | "opportunity_card";

export type ComplianceStatus = "approved" | "warning" | "blocked";

export type DistributorSource = "internal_curated" | "marketplace_api" | "research";

export type DistributorVerificationStatus =
  | "verified"
  | "unverified"
  | "flagged";

export type OpportunitySource =
  | "internal_curated"
  | "seller_center"
  | "marketplace_api"
  | "research";

export type CompetitionLevel = "low" | "medium" | "high";

/** P1.6-allowed source values per ADR-020 and issue #153 AC. */
export const P16_ALLOWED_SOURCES = ["internal_curated", "research"] as const;

export type P16AllowedSource = (typeof P16_ALLOWED_SOURCES)[number];

export interface ProductInfo {
  product_name: string;
  brand: string | null;
  category: string;
  price: number;
  variants: string[];
  description: string | null;
}

export interface ListingContent {
  title: string;
  description: string;
  bullet_points: string[];
  seo_keywords: string[];
  hashtags: string[];
}

export interface ComplianceResult {
  status: ComplianceStatus;
  warnings: string[];
  blocking_issues: string[];
}

export interface ReadinessResult {
  overall_score: number;
  suggested_improvements: string[];
}

export interface ProductDraft {
  draft_id: string;
  seller_id: string;
  shop_id: string;
  status: ProductDraftStatus;
  source_type: ProductDraftSourceType;
  product_info: ProductInfo;
  listing_content: ListingContent;
  compliance: ComplianceResult;
  readiness: ReadinessResult;
  created_at: string;
  updated_at: string;
}

export interface Distributor {
  distributor_id: string;
  name: string;
  category_coverage: string[];
  moq: number;
  lead_time_days: number;
  reliability_score: number;
  source: DistributorSource;
  verification_status: DistributorVerificationStatus;
}

export interface Opportunity {
  opportunity_id: string;
  product_name: string;
  category: string;
  estimated_demand: number;
  competition_level: CompetitionLevel;
  margin_potential: number;
  trend_score: number;
  suggested_supplier_ids: string[];
  confidence: number;
  source: OpportunitySource;
  /** P1.6 Path B filter: minimum seller capital (VND). */
  min_capital_vnd: number;
  /** P1.6 Path B filter: maximum seller capital (VND). */
  max_capital_vnd: number;
  /** P1.6 Path B filter: dropship eligibility. */
  supports_dropship: boolean;
}
