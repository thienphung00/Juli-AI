import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { channelSplit, metricView } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { OpsViewAs } from "../ops-view-as";
import { ME, SETTINGS, SHOP_ID, VIEW_SESSION } from "./fixtures";

/** W3.1 V-1: a TikTok shop in Xem như shop is on the shared screens; `?adr108=1` keeps the ADR-108 ones. */

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(search),
}));

beforeEach(() => {
  search = "";
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

const BASE = `/v1/ops/shops/${SHOP_ID}/shopee/analytics`;
const TIKTOK = { ...VIEW_SESSION, shop: { ...SETTINGS.shop, platform: "tiktok" } };
const SHOPEE = { ...VIEW_SESSION, shop: { ...SETTINGS.shop, platform: "shopee" } };

function opsFetch() {
  const urls: string[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    urls.push(url);
    const path = url.split("?")[0]!;
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (path === `${BASE}/channel-split`) return json(channelSplit());
    if (path === `${BASE}/metric-view`) return json(metricView({ metric: "gmv" }));
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  });
  return { fn: fn as unknown as typeof fetch, urls };
}

const open = (session: typeof TIKTOK, fn: typeof fetch) => render(<OpsViewAs api={{ viewSession: async () => session }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);

describe("Xem như shop on a TikTok shop", () => {
  it("V-1a · Trang chủ opens the shared Tổng quan, read through the Ops base, with TikTok source names", async () => {
    const { fn, urls } = opsFetch();
    open(TIKTOK, fn);
    await screen.findByTestId("sa-tile-gmv");
    expect(screen.getByTestId("sa-platform")).toHaveTextContent("TikTok Shop");
    expect(screen.getByTestId("sa-channel-organic_live")).toHaveTextContent("LIVE");
    expect(screen.getByTestId("sa-channel-organic_shop")).toHaveTextContent("Tab cửa hàng");
    expect(screen.queryByText("Trang shop")).toBeNull();
    // the rail only: the Tổng quan level toggle has its own "Sản phẩm" button
    const rail = within(screen.getByRole("navigation", { name: "Seller" }));
    for (const name of ["Tổng quan", "Phân tích", "Quyết định", "Quy tắc"]) expect(rail.getByRole("button", { name })).toBeInTheDocument();
    for (const name of ["Trang chủ", "Sản phẩm"]) expect(rail.queryByRole("button", { name })).toBeNull();
    expect(urls.some((u) => u.startsWith(`${BASE}/channel-split`))).toBe(true);
    expect(urls.some((u) => u.includes("/analysis"))).toBe(false);
  });

  it("V-1a · an old trang=trang-chu link also lands on Tổng quan", async () => {
    search = "trang=trang-chu";
    const { fn } = opsFetch();
    open(TIKTOK, fn);
    await screen.findByTestId("sa-tile-gmv");
  });

  it("V-1a · Phân tích is the shared screen", async () => {
    search = "trang=phan-tich&metric=gmv";
    const { fn, urls } = opsFetch();
    open(TIKTOK, fn);
    await screen.findByTestId("pt-channels");
    expect(urls.some((u) => u.startsWith(`${BASE}/metric-view`))).toBe(true);
  });

  it("V-1b · ?adr108=1 keeps the old Trang chủ", async () => {
    search = "adr108=1&trang=trang-chu";
    const { fn, urls } = opsFetch();
    open(TIKTOK, fn);
    await screen.findByRole("button", { name: "Trang chủ" });
    await waitFor(() => expect(urls.some((u) => u.includes("/analysis"))).toBe(true));
    expect(screen.queryByTestId("sa-tile-gmv")).toBeNull();
    expect(urls.some((u) => u.startsWith(BASE))).toBe(false);
  });

  it("V-1b · ?adr108=1 keeps the old Phân tích", async () => {
    search = "adr108=1&trang=phan-tich";
    const { fn, urls } = opsFetch();
    open(TIKTOK, fn);
    await screen.findByRole("button", { name: "Trang chủ" });
    await waitFor(() => expect(urls.some((u) => u.includes("/analysis"))).toBe(true));
    expect(screen.queryByTestId("pt-channels")).toBeNull();
    expect(urls.some((u) => u.startsWith(BASE))).toBe(false);
  });
});

describe("Xem như shop on a Shopee shop (V-3)", () => {
  it("is unchanged: opens on Tổng quan with Shopee names", async () => {
    const { fn } = opsFetch();
    open(SHOPEE, fn);
    await screen.findByTestId("sa-tile-gmv");
    expect(screen.getByTestId("sa-platform")).toHaveTextContent("Shopee");
    expect(screen.getAllByRole("button", { name: "Sản phẩm" }).length).toBeGreaterThan(0);
  });
});
