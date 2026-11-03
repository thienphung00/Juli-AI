import { describe, expect, it, vi } from "vitest";

import { DEMO_SHOPEE_BASE, ShopeeApiError, createShopeeApi, opsShopeeBase, refusalOf } from "../client";

function respond(body: unknown, status = 200): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch;
}

describe("Shopee read API client", () => {
  it("reads the seller API with bearer and X-Shop-Id", async () => {
    const f = respond({ platform: "shopee" });
    await createShopeeApi({ base: DEMO_SHOPEE_BASE, token: "t", shopId: "s1", fetchImpl: f }).overview({ period: "30d" });
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/demo/shopee/overview?period=30d");
    expect(init.method).toBe("GET");
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s1" });
  });

  it("reads the Ops API without X-Shop-Id", async () => {
    const f = respond({});
    await createShopeeApi({ base: opsShopeeBase("a b"), token: "t", fetchImpl: f }).matrix({ period: "7d", sort: "bien" });
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/ops/shops/a%20b/shopee/analytics/matrix?period=7d&sort=bien");
    expect((init.headers as Record<string, string>)["X-Shop-Id"]).toBeUndefined();
  });

  it("sends a month and a custom window as the API names them", async () => {
    const f = respond({});
    const api = createShopeeApi({ base: DEMO_SHOPEE_BASE, token: "t", shopId: "s", fetchImpl: f });
    await api.critical({ period: "month", month: "2026-10" });
    await api.critical({ period: "custom", from: "2026-10-01", to: "2026-10-20" });
    const urls = (f as unknown as ReturnType<typeof vi.fn>).mock.calls.map((c) => c[0]);
    expect(urls).toEqual(["/v1/demo/shopee/critical?period=month&month=2026-10", "/v1/demo/shopee/critical?period=custom&from=2026-10-01&to=2026-10-20"]);
  });

  it("asks a ranking with kind, source, sub and xep_theo", async () => {
    const f = respond({});
    await createShopeeApi({ base: DEMO_SHOPEE_BASE, token: "t", shopId: "s", fetchImpl: f }).ranking({
      period: "30d",
      kind: "products",
      source: "the_san_pham_khac",
      sub: "recommend",
      xepTheo: "bien",
    });
    expect((f as unknown as ReturnType<typeof vi.fn>).mock.calls[0]![0]).toBe(
      "/v1/demo/shopee/ranking?period=30d&kind=products&source=the_san_pham_khac&sub=recommend&xep_theo=bien",
    );
  });

  it("reads a product by id and period", async () => {
    const f = respond({});
    await createShopeeApi({ base: DEMO_SHOPEE_BASE, token: "t", shopId: "s", fetchImpl: f }).product("BEP-S5", "90d");
    expect((f as unknown as ReturnType<typeof vi.fn>).mock.calls[0]![0]).toBe("/v1/demo/shopee/products/BEP-S5?period=90d");
  });

  it("turns the API's refusals into typed errors", async () => {
    const api = (body: unknown, status: number) => createShopeeApi({ base: DEMO_SHOPEE_BASE, token: "t", shopId: "s", fetchImpl: respond(body, status) });
    const notShopee = await api({ detail: { code: "not_a_shopee_shop", message: "x" } }, 409).overview({ period: "30d" }).catch((e: unknown) => e);
    expect(notShopee).toBeInstanceOf(ShopeeApiError);
    expect(refusalOf(notShopee)).toBe("not-shopee");
    expect(refusalOf(await api({ detail: { code: "no_shopee_data", message: "x" } }, 409).overview({ period: "30d" }).catch((e: unknown) => e))).toBe("no-data");
    expect(refusalOf(await api({ detail: { code: "product_not_found", message: "x" } }, 404).product("X", "30d").catch((e: unknown) => e))).toBe("not-found");
    expect(refusalOf(await api({ detail: { code: "invalid_period", message: "x" } }, 422).overview({ period: "30d" }).catch((e: unknown) => e))).toBe("invalid");
    expect(refusalOf(await api({}, 500).overview({ period: "30d" }).catch((e: unknown) => e))).toBe("failed");
    expect(refusalOf(new Error("boom"))).toBe("failed");
  });
});
