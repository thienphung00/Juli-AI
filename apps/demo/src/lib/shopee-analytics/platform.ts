"use client";

import { useCallback, useEffect, useState } from "react";

import type { NavPlatform } from "../app-navigation";
import type { ShopReportState } from "../shop-report/shop-report-context";

/**
 * Which marketplace the acting shop is on, for the seller shell's navigation, header and screens (ADR-120 d.2).
 *
 * The answer comes ONLY from `GET /v1/shops/me` (`platform`: "tiktok" | "shopee"). Nothing is guessed from another
 * route: the Shopee read routes answer TikTok shops too (W3), so a 409 or a 200 there says nothing about the
 * marketplace. An answer is kept per shop for the page's lifetime.
 *
 * A read that fails or stalls leaves the platform UNKNOWN, never "tiktok": a Shopee shop must not render as TikTok.
 * The hook retries a bounded number of times with growing pauses, then reports `phase: "error"` so the screen can
 * offer a retry button.
 */

const known = new Map<string, NavPlatform>();

/** How long one `shops/me` read may stay open. */
export const PLATFORM_READ_TIMEOUT_MS = 8_000;
/** Reads before giving up, and the pauses between them (bounded backoff). */
export const PLATFORM_ATTEMPTS = 3;
export const PLATFORM_BACKOFF_MS: readonly number[] = [1_000, 3_000];

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

/** One read of the platform: the answer, or null when unknown (failed, malformed, or no answer in time). */
export function probeShopPlatform(token: string, shopId: string, fetchImpl?: typeof fetch): Promise<NavPlatform | null> {
  const cached = known.get(shopId);
  if (cached) return Promise.resolve(cached);
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), PLATFORM_READ_TIMEOUT_MS);
    void platformFromShopsMe(token, shopId, fetchImpl).then((platform) => {
      clearTimeout(timer);
      if (platform) known.set(shopId, platform);
      resolve(platform);
    });
  });
}

/** Test hook: forget what was learned. */
export function resetShopPlatformCache(): void {
  known.clear();
}

export type PlatformPhase = "none" | "loading" | "ready" | "error";

export interface ShopPlatformState {
  /** The platform when `phase` is "ready" (or "none": no shop, so TikTok's landing); null while loading or failed. */
  readonly platform: NavPlatform | null;
  readonly phase: PlatformPhase;
  /** After "error": ask again from the start. */
  readonly retry: () => void;
}

/**
 * The acting shop's platform as a phase: `none` without a shop (anonymous, no-shop: TikTok's landing screens),
 * `loading` while the shell resolves the session or `shops/me` is being asked (bounded retries), `ready` with the
 * answer, `error` when every read failed.
 */
export function useShopPlatformState(state: ShopReportState | null, fetchImpl?: typeof fetch): ShopPlatformState {
  const shopId = state && "shop" in state ? state.shop.id : null;
  const token = state && "token" in state ? state.token : null;
  const [round, setRound] = useState(0);
  const [answer, setAnswer] = useState<{ shopId: string; round: number; platform: NavPlatform | null } | null>(null);
  const retry = useCallback(() => setRound((r) => r + 1), []);

  useEffect(() => {
    if (!shopId || !token) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const attempt = (n: number) => {
      void probeShopPlatform(token, shopId, fetchImpl).then((platform) => {
        if (!live) return;
        if (platform || n + 1 >= PLATFORM_ATTEMPTS) {
          setAnswer({ shopId, round, platform });
          return;
        }
        timer = setTimeout(() => attempt(n + 1), PLATFORM_BACKOFF_MS[Math.min(n, PLATFORM_BACKOFF_MS.length - 1)]);
      });
    };
    attempt(0);
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [shopId, token, fetchImpl, round]);

  if (state?.status === "resolving") return { platform: null, phase: "loading", retry };
  if (!state || !shopId || !token) return { platform: "tiktok", phase: "none", retry };
  const cached = known.get(shopId);
  if (cached) return { platform: cached, phase: "ready", retry };
  if (answer && answer.shopId === shopId && answer.round === round) {
    return answer.platform ? { platform: answer.platform, phase: "ready", retry } : { platform: null, phase: "error", retry };
  }
  return { platform: null, phase: "loading", retry };
}

/** The platform, or null while it is unknown (loading or failed). Without a shop it is TikTok. */
export function useShopPlatformResolved(state: ShopReportState | null, fetchImpl?: typeof fetch): NavPlatform | null {
  return useShopPlatformState(state, fetchImpl).platform;
}
