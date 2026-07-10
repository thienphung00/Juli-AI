/**
 * Phase 1 rules baseline for seller lifecycle classification.
 * Phase 1.5 ML seller-stage classifier is compared against output from
 * `classifySellerStage()` using these constants.
 */
export const RETURN_RATE_LEAKAGE_MIN = 0.1;

/** Sellers at or below this 30-day order volume route to New Seller Copilot. */
export const ORDER_COUNT_NEW_MAX = 15;

/** Young shops below growth volume still route as new when age is at or below this. */
export const SHOP_AGE_NEW_MAX_DAYS = 45;

/** Minimum 30-day orders to qualify for Growth Copilot (with ad spend). */
export const ORDER_COUNT_GROWTH_MIN = 50;

/** Minimum 30-day ad spend (VND) to qualify for Growth Copilot. */
export const AD_SPEND_GROWTH_MIN_VND = 5_000_000;
