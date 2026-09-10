import { afterEach, describe, expect, it, vi } from "vitest";

import { SHOPS_API_PATH, ShopsFetchError, fetchShops } from "../shops-client";

describe("fetchShops", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls GET /v1/shops with a bearer token and no X-Shop-Id (none resolved yet)", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        {
          id: "shop-1",
          shop_name: "Cửa hàng của Lan",
          tiktok_shop_id: "tt-1",
          is_active: true,
        },
      ],
    });

    const shops = await fetchShops("real-access-token", fetchImpl as unknown as typeof fetch);

    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(SHOPS_API_PATH);
    expect((init as RequestInit).headers).toMatchObject({
      Authorization: "Bearer real-access-token",
    });
    expect((init as RequestInit).headers).not.toHaveProperty("X-Shop-Id");
    expect(shops).toEqual([
      {
        id: "shop-1",
        shop_name: "Cửa hàng của Lan",
        tiktok_shop_id: "tt-1",
        is_active: true,
      },
    ]);
  });

  it("surfaces the known-gap 401 (no public.users row yet) as a typed, honest error", async () => {
    const fetchImpl = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ detail: "User not found" }),
    });

    await expect(
      fetchShops("real-access-token", fetchImpl as unknown as typeof fetch),
    ).rejects.toMatchObject(
      new ShopsFetchError(401, "User not found"),
    );
  });

  it("never falls back to fixture content on failure", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("network down"));

    await expect(
      fetchShops("real-access-token", fetchImpl as unknown as typeof fetch),
    ).rejects.toThrow();
  });
});
