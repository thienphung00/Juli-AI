import type { SellerProfile } from "@/lib/mock-data/seller-personas/schemas";

/** Minimum delivered-order signal for "first sale" in Phase 1 mock data. */
export const FIRST_SALE_ORDER_TARGET = 1;

/** Representative GMV threshold (VND) for a profitable first sale. */
export const FIRST_SALE_GMV_TARGET_VND = 500_000;

export interface FirstSaleMilestone {
  percent: number;
  ordersProgress: number;
  gmvProgress: number;
  hasFirstSale: boolean;
  orderCount: number;
  gmvVnd: number;
}

export function computeFirstSaleMilestone(profile: SellerProfile): FirstSaleMilestone {
  const ordersProgress = Math.min(profile.order_count_30d / FIRST_SALE_ORDER_TARGET, 1);
  const gmvProgress = Math.min(profile.gmv_30d_vnd / FIRST_SALE_GMV_TARGET_VND, 1);
  const percent = Math.round(((ordersProgress + gmvProgress) / 2) * 100);
  const hasFirstSale = ordersProgress >= 1 && gmvProgress >= 1;

  return {
    percent,
    ordersProgress,
    gmvProgress,
    hasFirstSale,
    orderCount: profile.order_count_30d,
    gmvVnd: profile.gmv_30d_vnd,
  };
}
