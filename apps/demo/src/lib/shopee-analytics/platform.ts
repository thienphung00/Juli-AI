"use client";

import { useEffect, useState } from "react";

import type { NavPlatform } from "../app-navigation";
import type { ShopReportState } from "../shop-report/shop-report-context";
import { DEMO_SHOPEE_BASE, ShopeeApiError, createShopeeApi } from "./client";

/**
 * Which marketplace the acting shop is on, for the seller shell's navigation (ADR-120 d.2).
 *
 * `GET /v1/shops/me` carries no platform yet, so the shell asks the Shopee read API itself:
 * `/v1/demo/shopee/*` answers a TikTok shop with 409 `not_a_shopee_shop` before it reads
 * anything, and answers a Shopee shop with data (or 409 `no_shopee_data`). The answer is kept per
 * shop for the page's lifetime; an unclear failure is treated as TikTok and not remembered.
 * When `shops/me` returns `platform`, swap this probe for it (one place).
 */

const known = new Map<string, NavPlatform>();

export async function probeShopPlatform(
  token: string,
  shopId: string,
  fetchImpl?: typeof fetch,
): Promise<NavPlatform | null> {
  const cached = known.get(shopId);
  if (cached) return cached;
  try {
    await createShopeeApi({ base: DEMO_SHOPEE_BASE, token, shopId, fetchImpl }).overview({ period: "30d" });
    known.set(shopId, "shopee");
    return "shopee";
  } catch (error) {
    if (error instanceof ShopeeApiError && error.status === 409) {
      const platform = error.code === "not_a_shopee_shop" ? "tiktok" : "shopee";
      known.set(shopId, platform);
      return platform;
    }
    return null;
  }
}

/** Test hook: forget what was learned. */
export function resetShopPlatformCache(): void {
  known.clear();
}

export function useShopPlatform(state: ShopReportState, fetchImpl?: typeof fetch): NavPlatform {
  const shopId = "shop" in state ? state.shop.id : null;
  const token = "token" in state ? state.token : null;
  const [answer, setAnswer] = useState<{ shopId: string; platform: NavPlatform } | null>(null);
  useEffect(() => {
    if (!shopId || !token) return;
    let live = true;
    void probeShopPlatform(token, shopId, fetchImpl).then((platform) => {
      if (live && platform) setAnswer({ shopId, platform });
    });
    return () => {
      live = false;
    };
  }, [shopId, token, fetchImpl]);
  if (!shopId) return "tiktok";
  return answer && answer.shopId === shopId ? answer.platform : (known.get(shopId) ?? "tiktok");
}
