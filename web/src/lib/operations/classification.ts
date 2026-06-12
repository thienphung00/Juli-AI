import type {
  ShopProfileType,
  UnifiedOperationalDataModel,
} from "@/lib/mock-data/operations/schemas";

import {
  GMV_METRICS_MIN_COUNT,
  SHOP_AGE_MID_LARGE_MIN_DAYS,
} from "./thresholds";

export type ShopProfileClassification = ShopProfileType;

function hasActiveProbation(model: UnifiedOperationalDataModel): boolean {
  return model.shop_metadata.probation_status === "active";
}

function hasMetGraduationRequirements(model: UnifiedOperationalDataModel): boolean {
  if (hasActiveProbation(model)) {
    return false;
  }

  if (model.probation === null) {
    return (
      model.shop_metadata.probation_status === "graduated" ||
      model.shop_metadata.probation_status === "not_applicable"
    );
  }

  const { sps_current, sps_threshold, ahr_current, ahr_threshold } = model.probation;
  return sps_current >= sps_threshold && ahr_current >= ahr_threshold;
}

function countGmvMetricsTracked(model: UnifiedOperationalDataModel): number {
  let count = 0;

  const productGmv30d = model.products.reduce(
    (sum, product) => sum + product.revenue_vnd_30d,
    0,
  );
  if (productGmv30d > 0) {
    count += 1;
  }

  const adRevenue = model.ad_campaigns.reduce(
    (sum, campaign) => sum + campaign.revenue_vnd,
    0,
  );
  if (adRevenue > 0) {
    count += 1;
  }

  const unitsSold30d = model.products.reduce(
    (sum, product) => sum + product.units_sold_30d,
    0,
  );
  if (unitsSold30d > 0) {
    count += 1;
  }

  const adSpend = model.ad_campaigns.reduce(
    (sum, campaign) => sum + campaign.spend_vnd,
    0,
  );
  if (adSpend > 0) {
    count += 1;
  }

  return count;
}

function qualifiesAsMidLargeShop(model: UnifiedOperationalDataModel): boolean {
  if (!hasMetGraduationRequirements(model)) {
    return false;
  }

  if (model.shop_metadata.shop_age_days >= SHOP_AGE_MID_LARGE_MIN_DAYS) {
    return true;
  }

  return countGmvMetricsTracked(model) >= GMV_METRICS_MIN_COUNT;
}

/**
 * Rules-based operations shop profile classifier (P1.8-1).
 * Extends — does not replace — demo persona routing in `seller-stage-router`.
 */
export function classifyShopProfile(
  unifiedModel: UnifiedOperationalDataModel,
): ShopProfileClassification {
  if (qualifiesAsMidLargeShop(unifiedModel)) {
    return "MID_LARGE_SHOP";
  }

  return "NEW_SHOP";
}
