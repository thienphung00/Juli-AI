"use client";

import { useRouter } from "next/navigation";
import { useEffect, useSyncExternalStore } from "react";

import type { ShopReportState } from "./shop-report/shop-report-context";
import { useShopPlatformResolved } from "./shopee-analytics/platform";
import { tiktokLegacyScreens } from "./tiktok-screens";

/**
 * W3 U-2/U-4: a signed-in TikTok shop opening the ADR-108 `/` or `/analytics` is sent to the shared
 * Tổng quan / Phân tích (`/tong-quan`, `/phan-tich`), unless the one switch (`tiktokLegacyScreens`) keeps the
 * old screens. Returns true while the page must not render the old screen yet (platform or switch not known,
 * or the redirect is under way), so ADR-108 never flashes at a shop that is leaving it.
 */
const subscribeNever = () => () => undefined;
const legacySnapshot = (): boolean => tiktokLegacyScreens(new URLSearchParams(window.location.search));
const serverSnapshot = (): boolean | null => null;

export function useTiktokSharedRedirect(state: ShopReportState, target: "/tong-quan" | "/phan-tich"): boolean {
  const router = useRouter();
  const platform = useShopPlatformResolved(state);
  // Read from the URL on the client only (the server has no URL: null there, so hydration matches).
  const legacy = useSyncExternalStore(subscribeNever, legacySnapshot, serverSnapshot);
  const hasShop = "shop" in state;

  const redirect = hasShop && legacy === false && platform === "tiktok";
  useEffect(() => {
    if (redirect) router.replace(target);
  }, [redirect, router, target]);

  if (!hasShop) return false;
  if (legacy === null) return true;
  if (legacy) return false;
  return platform === null || redirect;
}
