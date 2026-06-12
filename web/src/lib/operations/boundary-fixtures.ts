import { loadOperationalModel } from "@/lib/mock-data/operations";
import type { UnifiedOperationalDataModel } from "@/lib/mock-data/operations/schemas";
import type { ShopProfileClassification } from "./classification";

export interface ProfileBoundaryFixture {
  id: string;
  expectedProfile: ShopProfileClassification;
  model: UnifiedOperationalDataModel;
  note: string;
}

/**
 * Golden boundary profiles for QA — each row sits on or adjacent to a threshold.
 */
export const PROFILE_BOUNDARY_FIXTURES: ProfileBoundaryFixture[] = [
  {
    id: "boundary-active-probation",
    expectedProfile: "NEW_SHOP",
    model: loadOperationalModel("NEW_SHOP"),
    note: "Active probation with unmet SPS/AHR thresholds",
  },
  {
    id: "boundary-unmet-graduation-scores",
    expectedProfile: "NEW_SHOP",
    model: {
      ...loadOperationalModel("NEW_SHOP"),
      shop_metadata: {
        ...loadOperationalModel("NEW_SHOP").shop_metadata,
        probation_status: "active",
        shop_age_days: 100,
      },
      probation: {
        probation_start_date: "2026-01-01T00:00:00.000Z",
        probation_end_date: "2026-07-01T00:00:00.000Z",
        sps_current: 3.9,
        sps_threshold: 4.0,
        ahr_current: 89,
        ahr_threshold: 90,
        violations: [],
      },
    },
    note: "Active probation with SPS/AHR just below graduation thresholds",
  },
  {
    id: "boundary-graduated-mid-large-age",
    expectedProfile: "MID_LARGE_SHOP",
    model: loadOperationalModel("MID_LARGE_SHOP"),
    note: "Graduated probation with 90+ days active",
  },
  {
    id: "boundary-graduated-young-with-gmv-metrics",
    expectedProfile: "MID_LARGE_SHOP",
    model: {
      ...loadOperationalModel("MID_LARGE_SHOP"),
      shop_metadata: {
        ...loadOperationalModel("MID_LARGE_SHOP").shop_metadata,
        shop_age_days: 60,
        probation_status: "graduated",
      },
      probation: null,
    },
    note: "Graduated shop under 90 days but with ≥2 GMV metrics tracked",
  },
  {
    id: "boundary-graduated-young-insufficient-gmv",
    expectedProfile: "NEW_SHOP",
    model: {
      ...loadOperationalModel("NEW_SHOP"),
      shop_metadata: {
        shop_id: "shop_transitional_001",
        shop_name: "Transitional Shop",
        profile: "NEW_SHOP",
        probation_status: "graduated",
        graduation_date: "2026-05-01T00:00:00.000Z",
        shop_age_days: 45,
      },
      probation: null,
      ad_campaigns: [],
      products: [
        {
          product_id: "prod_trans_001",
          sku_id: "sku_trans_001",
          product_name: "Starter SKU",
          category: "Accessories",
          units_sold_24h: 0,
          units_sold_7d: 0,
          units_sold_30d: 0,
          revenue_vnd_24h: 0,
          revenue_vnd_7d: 0,
          revenue_vnd_30d: 300_000,
          price_vnd: 150_000,
          margin_pct: 30,
          sell_through_rate: 0.1,
        },
      ],
    },
    note: "Graduated but young with only one GMV metric — stays NEW_SHOP",
  },
];
