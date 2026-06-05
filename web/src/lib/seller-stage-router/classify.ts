import type { PersonaId, SellerProfile } from "@/lib/mock-data/seller-personas/schemas";
import {
  AD_SPEND_GROWTH_MIN_VND,
  ORDER_COUNT_GROWTH_MIN,
  ORDER_COUNT_NEW_MAX,
  RETURN_RATE_LEAKAGE_MIN,
  SHOP_AGE_NEW_MAX_DAYS,
} from "./thresholds";

export type SellerStage = PersonaId;

export type SellerStageInput = Pick<
  SellerProfile,
  "shop_age_days" | "order_count_30d" | "return_rate_30d" | "ad_spend_30d_vnd"
>;

/**
 * Deterministic rules-based seller lifecycle classifier.
 * Priority: leakage (elevated returns) → new (low volume / young shop) → growth.
 */
export function classifySellerStage(profile: SellerStageInput): SellerStage {
  const {
    shop_age_days: shopAgeDays,
    order_count_30d: orderCount30d,
    return_rate_30d: returnRate30d,
    ad_spend_30d_vnd: adSpend30dVnd,
  } = profile;

  if (
    returnRate30d >= RETURN_RATE_LEAKAGE_MIN &&
    orderCount30d > ORDER_COUNT_NEW_MAX
  ) {
    return "leakage";
  }

  if (
    orderCount30d <= ORDER_COUNT_NEW_MAX ||
    (shopAgeDays <= SHOP_AGE_NEW_MAX_DAYS &&
      orderCount30d < ORDER_COUNT_GROWTH_MIN)
  ) {
    return "new";
  }

  if (
    orderCount30d >= ORDER_COUNT_GROWTH_MIN &&
    adSpend30dVnd >= AD_SPEND_GROWTH_MIN_VND
  ) {
    return "growth";
  }

  return "growth";
}
