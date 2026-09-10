/**
 * `GET /v1/shops` — the only authenticated Juli backend call the connect-shop
 * screen makes (issue #1319). Same-origin relative path, matching the
 * existing `apps/demo` contract (#397, see `lib/analytics/api-client.ts`) —
 * no client-side API base env var.
 *
 * A 401 here is the documented, in-scope known gap: a first-time Google user
 * has no `public.users` row yet (`get_current_user` → `NotFound` → 401 "User
 * not found"). This module surfaces that honestly as a typed error; it must
 * never be caught and papered over with fixture content.
 */

export const SHOPS_API_PATH = "/v1/shops" as const;

export interface Shop {
  id: string;
  shop_name: string;
  tiktok_shop_id: string | null;
  is_active: boolean;
}

export class ShopsFetchError extends Error {
  constructor(
    public readonly status: number,
    detail?: string,
  ) {
    super(detail ?? `Shops fetch failed (${status})`);
    this.name = "ShopsFetchError";
  }
}

export async function fetchShops(
  accessToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<Shop[]> {
  const response = await fetchImpl(SHOPS_API_PATH, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    let detail: string | undefined;

    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail;
    } catch {
      detail = undefined;
    }

    throw new ShopsFetchError(response.status, detail);
  }

  return (await response.json()) as Shop[];
}
