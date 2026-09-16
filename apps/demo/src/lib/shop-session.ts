/**
 * The acting shop for the signed-in door (issue #1909, #1319's surviving
 * criterion): every authenticated `/v1/*` call the demo makes is scoped by
 * an `X-Shop-Id` header the backend ownership-checks (`get_active_shop`),
 * and a seller with more than one shop must be able to tell which shop
 * they are acting as. The connect-shop screen writes this record when the
 * seller picks a shop; the signed-in Decisions and run surfaces read it —
 * one source of truth, `sessionStorage`, same lifetime as the auth session
 * it accompanies (`supabase-auth.ts`'s `AUTH_SESSION_STORAGE_KEY`).
 *
 * Pure browser-storage module: no network call site, no `/v1/*` route
 * literal — safe in any module graph, including the anonymous replay
 * door's (ADR-094 decision 1), though nothing on that door reads it.
 */

export const ACTIVE_SHOP_STORAGE_KEY = "juli_demo_active_shop";

interface ActiveShop {
  id: string;
  name: string;
}

export function storeActiveShop(shop: ActiveShop): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(ACTIVE_SHOP_STORAGE_KEY, JSON.stringify(shop));
}

export function readActiveShop(): ActiveShop | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(ACTIVE_SHOP_STORAGE_KEY);

  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<ActiveShop>;

    if (typeof parsed.id !== "string" || parsed.id.length === 0) {
      return null;
    }

    return { id: parsed.id, name: typeof parsed.name === "string" ? parsed.name : "" };
  } catch {
    return null;
  }
}

export function clearActiveShop(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.removeItem(ACTIVE_SHOP_STORAGE_KEY);
}
