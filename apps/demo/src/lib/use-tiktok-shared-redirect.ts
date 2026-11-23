"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { ShopReportState } from "./shop-report/shop-report-context";
import { useShopPlatformResolved } from "./shopee-analytics/platform";
import { tiktokLegacyScreens } from "./tiktok-screens";

/**
 * W3 U-2/U-4: a signed-in TikTok shop opening the ADR-108 `/` or `/analytics` is sent to the shared
 * Tổng quan / Phân tích (`/tong-quan`, `/phan-tich`), unless the one switch (`tiktokLegacyScreens`) keeps the
 * old screens. Returns true while the page must not render the old screen yet (platform or switch not known,
 * or the redirect is under way), so ADR-108 never flashes at a shop that is leaving it.
 */
export function useTiktokSharedRedirect(state: ShopReportState, target: "/tong-quan" | "/phan-tich"): boolean {
  const router = useRouter();
  const platform = useShopPlatformResolved(state);
  const [legacy, setLegacy] = useState<boolean | null>(null);
  const hasShop = "shop" in state;

  useEffect(() => {
    // Read after mount: the server has no URL, and the first client render must match it.
    setLegacy(tiktokLegacyScreens(new URLSearchParams(window.location.search)));
  }, []);

  const redirect = hasShop && legacy === false && platform === "tiktok";
  useEffect(() => {
    if (redirect) router.replace(target);
  }, [redirect, router, target]);

  if (!hasShop) return false;
  if (legacy === null) return true;
  if (legacy) return false;
  return platform === null || redirect;
}
