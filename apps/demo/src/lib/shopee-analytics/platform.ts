"use client";

import { useEffect, useState } from "react";

import type { NavPlatform } from "../app-navigation";
import type { ShopReportState } from "../shop-report/shop-report-context";
import { DEMO_SHOPEE_BASE, ShopeeApiError, createShopeeApi } from "./client";

/**
 * Which marketplace the acting shop is on, for the seller shell's navigation and header (ADR-120 d.2).
 *
 * `GET /v1/shops/me` returns `platform` ("tiktok" | "shopee"); that is read first. A backend that
 * does not send it yet is probed through the Shopee read API instead: `/v1/demo/shopee/*` answers a
 * TikTok shop with 409 `not_a_shopee_shop` before it reads anything, and answers a Shopee shop with
 * data (or 409 `no_shopee_data`). The answer is kept per shop for the page's lifetime; an unclear
 * failure is treated as TikTok and not remembered.
 */

const known = new Map<string, NavPlatform>();

async function platformFromShopsMe(token: string, shopId: string, fetchImpl?: typeof fetch): Promise<NavPlatform | null> {
  try {
    const response = await (fetchImpl ?? fetch)("/v1/shops/me", {
      method: "GET",
      headers: { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopId },
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { platform?: unknown } | null;
    return body?.platform === "shopee" ? "shopee" : body?.platform === "tiktok" ? "tiktok" : null;
  } catch {
    return null;
  }
}

export async function probeShopPlatform(
  token: string,
  shopId: string,
  fetchImpl?: typeof fetch,
): Promise<NavPlatform | null> {
  const cached = known.get(shopId);
  if (cached) return cached;
  const declared = await platformFromShopsMe(token, shopId, fetchImpl);
  if (declared) {
    known.set(shopId, declared);
    return declared;
  }
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

/**
 * The acting shop's platform, or `null` while it is still being asked (a screen that must not flash
 * the wrong marketplace waits for the answer). Without a shop (`state` null, anonymous, no-shop) it is
 * TikTok at once; while the shell is still resolving who the shop is, `null`.
 */
export function useShopPlatformResolved(state: ShopReportState | null, fetchImpl?: typeof fetch): NavPlatform | null {
  const shopId = state && "shop" in state ? state.shop.id : null;
  const token = state && "token" in state ? state.token : null;
  const [answer, setAnswer] = useState<{ shopId: string; platform: NavPlatform } | null>(null);
  useEffect(() => {
    if (!shopId || !token) return;
    let live = true;
    void probeShopPlatform(token, shopId, fetchImpl).then((platform) => {
      if (live) setAnswer({ shopId, platform: platform ?? "tiktok" });
    });
    return () => {
      live = false;
    };
  }, [shopId, token, fetchImpl]);
  if (state?.status === "resolving") return null;
  if (!state || !shopId || !token) return "tiktok";
  return known.get(shopId) ?? (answer && answer.shopId === shopId ? answer.platform : null);
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
