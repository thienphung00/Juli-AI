import { useMemo, useSyncExternalStore } from "react";

/**
 * D27.8: the shop last chosen in Tổng quan, remembered per browser so the main-nav
 * "Mô phỏng" opens it. Storage can be missing or throw (private mode): every access
 * is guarded and a failure just means "no shop chosen".
 */
export const CURRENT_SHOP_KEY = "ops.currentShop";

export interface CurrentShop {
  readonly id: string;
  readonly name: string;
}

function readRaw(): string | null {
  try {
    return window.localStorage.getItem(CURRENT_SHOP_KEY);
  } catch {
    return null;
  }
}

function parse(raw: string | null): CurrentShop | null {
  try {
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && typeof (parsed as CurrentShop).id === "string" && (parsed as CurrentShop).id) {
      const p = parsed as CurrentShop;
      return { id: p.id, name: typeof p.name === "string" ? p.name : "" };
    }
    return null;
  } catch {
    return null;
  }
}

export function readCurrentShop(): CurrentShop | null {
  return parse(readRaw());
}

const SERVER = "\u0000server";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("storage", onChange);
  return () => window.removeEventListener("storage", onChange);
}

/** The remembered shop; `undefined` until the browser has been read (server render / hydration). */
export function useCurrentShop(): CurrentShop | null | undefined {
  const raw = useSyncExternalStore(subscribe, readRaw, () => SERVER);
  return useMemo(() => (raw === SERVER ? undefined : parse(raw)), [raw]);
}

export function writeCurrentShop(shop: CurrentShop): void {
  try {
    window.localStorage.setItem(CURRENT_SHOP_KEY, JSON.stringify({ id: shop.id, name: shop.name }));
  } catch {
    // storage unavailable: the choice just isn't remembered
  }
}
