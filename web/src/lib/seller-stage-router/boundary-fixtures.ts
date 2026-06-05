import type { SellerStageInput } from "./classify";

export interface StageBoundaryFixture {
  id: string;
  expectedStage: "new" | "leakage" | "growth";
  profile: SellerStageInput;
  note: string;
}

/**
 * Golden boundary profiles for QA — each row sits on or adjacent to a threshold.
 */
export const STAGE_BOUNDARY_FIXTURES: StageBoundaryFixture[] = [
  {
    id: "boundary-new-max-orders",
    expectedStage: "new",
    profile: {
      shop_age_days: 60,
      order_count_30d: 15,
      return_rate_30d: 0.05,
      ad_spend_30d_vnd: 2_000_000,
    },
    note: "Exactly at ORDER_COUNT_NEW_MAX (15) — still new",
  },
  {
    id: "boundary-new-young-shop",
    expectedStage: "new",
    profile: {
      shop_age_days: 45,
      order_count_30d: 30,
      return_rate_30d: 0.04,
      ad_spend_30d_vnd: 1_000_000,
    },
    note: "At SHOP_AGE_NEW_MAX_DAYS with sub-growth volume",
  },
  {
    id: "boundary-leakage-return-rate",
    expectedStage: "leakage",
    profile: {
      shop_age_days: 120,
      order_count_30d: 16,
      return_rate_30d: 0.1,
      ad_spend_30d_vnd: 3_000_000,
    },
    note: "Exactly at RETURN_RATE_LEAKAGE_MIN with established volume",
  },
  {
    id: "boundary-leakage-above-threshold",
    expectedStage: "leakage",
    profile: {
      shop_age_days: 200,
      order_count_30d: 91,
      return_rate_30d: 0.189,
      ad_spend_30d_vnd: 8_000_000,
    },
    note: "Just below leakage persona return rate",
  },
  {
    id: "boundary-growth-orders",
    expectedStage: "growth",
    profile: {
      shop_age_days: 365,
      order_count_30d: 50,
      return_rate_30d: 0.04,
      ad_spend_30d_vnd: 5_000_000,
    },
    note: "Exactly at ORDER_COUNT_GROWTH_MIN and AD_SPEND_GROWTH_MIN_VND",
  },
  {
    id: "boundary-not-leakage-below-return",
    expectedStage: "growth",
    profile: {
      shop_age_days: 180,
      order_count_30d: 80,
      return_rate_30d: 0.099,
      ad_spend_30d_vnd: 10_000_000,
    },
    note: "Just below RETURN_RATE_LEAKAGE_MIN — routes to growth",
  },
];
