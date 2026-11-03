import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopReportState } from "../../shop-report/shop-report-context";
import { probeShopPlatform, resetShopPlatformCache, useShopPlatform } from "../platform";

function respond(status: number, body: unknown): typeof fetch {
  return vi.fn(async () => new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;
}

beforeEach(() => resetShopPlatformCache());

describe("which marketplace the acting shop is on", () => {
  it("shops/me carrying a platform decides, with no probe", async () => {
    const f = respond(200, { platform: "shopee" });
    expect(await probeShopPlatform("t", "s0", f)).toBe("shopee");
    const calls = (f as unknown as ReturnType<typeof vi.fn>).mock.calls as [string, RequestInit][];
    expect(calls).toHaveLength(1);
    expect(calls[0]![0]).toBe("/v1/shops/me");
    expect(calls[0]![1].headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s0" });
    expect(await probeShopPlatform("t", "s0b", respond(200, { platform: "tiktok" }))).toBe("tiktok");
  });

  it("a shop the Shopee API answers is Shopee (shops/me without platform falls back to the probe)", async () => {
    const f = vi.fn(async (url: string) => (url === "/v1/shops/me" ? new Response(JSON.stringify({ id: "s1" }), { status: 200 }) : new Response("{}", { status: 200 }))) as unknown as typeof fetch;
    expect(await probeShopPlatform("t", "s1", f)).toBe("shopee");
    const [url, init] = (f as unknown as ReturnType<typeof vi.fn>).mock.calls[1] as [string, RequestInit];
    expect(url).toBe("/v1/demo/shopee/overview?period=30d");
    expect(init.headers).toMatchObject({ Authorization: "Bearer t", "X-Shop-Id": "s1" });
  });

  it("a shop with no data yet is still Shopee", async () => {
    expect(await probeShopPlatform("t", "s2", respond(409, { detail: { code: "no_shopee_data", message: "x" } }))).toBe("shopee");
  });

  it("409 not_a_shopee_shop is TikTok", async () => {
    expect(await probeShopPlatform("t", "s3", respond(409, { detail: { code: "not_a_shopee_shop", message: "x" } }))).toBe("tiktok");
  });

  it("an unclear failure is not remembered and not Shopee", async () => {
    expect(await probeShopPlatform("t", "s4", respond(500, {}))).toBeNull();
    expect(await probeShopPlatform("t", "s4", respond(200, {}))).toBe("shopee");
  });

  it("remembers the answer per shop", async () => {
    const f = respond(200, { platform: "shopee" });
    await probeShopPlatform("t", "s5", f);
    await probeShopPlatform("t", "s5", f);
    expect((f as unknown as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });

  it("the hook answers tiktok until proven otherwise, then shopee", async () => {
    const f = respond(200, {});
    const state: ShopReportState = { status: "empty", token: "t", shop: { id: "s6", name: "Shop" } };
    function Probe() {
      return <span data-testid="p">{useShopPlatform(state, f)}</span>;
    }
    render(<Probe />);
    expect(screen.getByTestId("p")).toHaveTextContent("tiktok");
    await waitFor(() => expect(screen.getByTestId("p")).toHaveTextContent("shopee"));
  });

  it("anonymous visitors and sessions without a shop never probe", async () => {
    const f = respond(200, {});
    function Probe({ state }: { state: ShopReportState }) {
      return <span data-testid="p">{useShopPlatform(state, f)}</span>;
    }
    render(<Probe state={{ status: "anonymous", envelope: null }} />);
    render(<Probe state={{ status: "no-shop", token: "t" }} />);
    expect(f).not.toHaveBeenCalled();
    expect(screen.getAllByTestId("p").map((e) => e.textContent)).toEqual(["tiktok", "tiktok"]);
  });
});
