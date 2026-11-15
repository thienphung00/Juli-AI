/**
 * `GET /v1/businesses` (P101 W1): the signed-in seller's businesses, each with the shops they may
 * open. Feeds the header switcher (Business ▾ → Shop ▾). Same-origin relative path, like
 * `shops-client.ts`.
 */

import { platformOf, type ShopPlatform } from "./shop-platform";

export const BUSINESSES_API_PATH = "/v1/businesses" as const;

export interface BusinessShop {
  readonly id: string;
  readonly name: string;
  readonly platform: ShopPlatform;
  readonly kind: "real" | "sandbox" | "sample";
}

export interface Business {
  /** `null`: a shop that has no business yet (listed on its own). */
  readonly id: string | null;
  readonly name: string;
  readonly role: "owner" | "member" | null;
  readonly shops: readonly BusinessShop[];
}

interface RawShop {
  id?: unknown;
  name?: unknown;
  platform?: unknown;
  kind?: unknown;
}

interface RawBusiness {
  id?: unknown;
  name?: unknown;
  role?: unknown;
  shops?: unknown;
}

function shopOf(raw: RawShop): BusinessShop | null {
  if (typeof raw.id !== "string" || !raw.id) return null;
  const kind = raw.kind === "sandbox" || raw.kind === "sample" ? raw.kind : "real";
  return {
    id: raw.id,
    name: typeof raw.name === "string" ? raw.name : "",
    platform: platformOf(typeof raw.platform === "string" ? raw.platform : null),
    kind,
  };
}

export function parseBusinesses(payload: unknown): Business[] {
  const data = (payload as { data?: unknown } | null)?.data;
  if (!Array.isArray(data)) return [];
  return data.map((entry: RawBusiness) => ({
    id: typeof entry.id === "string" ? entry.id : null,
    name: typeof entry.name === "string" ? entry.name : "",
    role: entry.role === "owner" || entry.role === "member" ? entry.role : null,
    shops: Array.isArray(entry.shops)
      ? entry.shops.map((s: RawShop) => shopOf(s)).filter((s): s is BusinessShop => s !== null)
      : [],
  }));
}

/** The caller's businesses; `[]` on any refusal (a reviewer, an expired session). */
export async function fetchBusinesses(accessToken: string, fetchImpl: typeof fetch = fetch): Promise<Business[]> {
  try {
    const response = await fetchImpl(BUSINESSES_API_PATH, {
      headers: { Accept: "application/json", Authorization: `Bearer ${accessToken}` },
      cache: "no-store",
    });
    if (!response.ok) return [];
    return parseBusinesses(await response.json());
  } catch {
    return [];
  }
}

/** The business holding `shopId`, else the first one. */
export function businessOfShop(businesses: readonly Business[], shopId: string | null): Business | null {
  if (shopId) {
    const found = businesses.find((b) => b.shops.some((s) => s.id === shopId));
    if (found) return found;
  }
  return businesses[0] ?? null;
}
