import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { channelProducts, channelSplit, critical, matrix, overview, product, ranking } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { OpsShopeeAnalytics } from "../shopee/ops-shopee-analytics";
import { OpsViewAs } from "../ops-view-as";
import { ME, SETTINGS, SHOP_ID, VIEW_SESSION } from "./fixtures";

/** Step 9: the Shopee shop screens inside Juli Ops, through the Ops API base. */

let search = "";
let replaced: string[] = [];
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: (href: string) => replaced.push(href), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(search),
}));

beforeEach(() => {
  search = "";
  replaced = [];
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

const BASE = `/v1/ops/shops/${SHOP_ID}/shopee/analytics`;

function opsFetch() {
  const calls: { url: string; headers: Record<string, string> }[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, headers: Object.fromEntries(new Headers(init?.headers).entries()) });
    const path = url.split("?")[0]!;
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (path === `${BASE}/overview`) return json(overview());
    if (path === `${BASE}/channel-split/products`) return json(channelProducts());
    if (path === `${BASE}/channel-split`) return json(channelSplit());
    if (path === `${BASE}/matrix`) return json(matrix());
    if (path === `${BASE}/critical`) return json(critical());
    if (path === `${BASE}/ranking`) return json(ranking());
    if (path.startsWith(`${BASE}/products/`)) return json(product());
    return new Response(JSON.stringify({ detail: "none" }), { status: 404 });
  });
  return { fn: fn as unknown as typeof fetch, calls };
}

const SHOPEE_SESSION = { ...VIEW_SESSION, shop: { ...SETTINGS.shop, platform: "shopee" } };

describe("Xem như shop on a Shopee shop", () => {
  it("shows the Shopee navigation and opens on Tổng quan, read through the Ops API", async () => {
    const { fn, calls } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("sa-tile-gmv");
    for (const name of ["Tổng quan", "Phân tích", "Sản phẩm", "Quyết định", "Quy tắc"]) {
      // the Tổng quan level toggle also has a "Sản phẩm" button
      expect(screen.getAllByRole("button", { name }).length).toBeGreaterThan(0);
    }
    for (const name of ["Trang chủ", "Juli"]) expect(screen.queryByRole("button", { name })).toBeNull();
    expect(screen.getByRole("button", { name: "Tổng quan" })).toHaveAttribute("aria-current", "page");
    const first = calls.find((c) => c.url.startsWith(`${BASE}/channel-split?`))!;
    expect(first.url).toBe(`${BASE}/channel-split?period=30d`);
    expect(first.headers.authorization).toBe("Bearer t");
    expect(first.headers["x-shop-id"]).toBeUndefined();
    expect(calls.every((c) => !c.url.startsWith("/v1/demo/shopee"))).toBe(true);
  });

  it("links between the screens stay inside the view-as page", async () => {
    const { fn } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    const tile = await screen.findByTestId("sa-tile-gmv");
    const href = tile.getAttribute("href")!;
    expect(href.startsWith(`/ops/shops/${SHOP_ID}/xem?`)).toBe(true);
    const p = new URLSearchParams(href.split("?")[1]);
    expect(p.get("trang")).toBe("phan-tich");
    expect(p.get("metric")).toBe("gmv");
    expect(p.get("from")).toBe("tong-quan");
  });

  it("opens the Phân tích of the Shopee shop, not the TikTok one", async () => {
    search = "trang=phan-tich";
    const { fn, calls } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sa-phan-tich")).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.startsWith(`${BASE}/critical`))).toBe(true));
  });

  it("opens a product by ?id=, and an old trang=xep-hang link opens Phân tích with its product table", async () => {
    search = "trang=san-pham&id=BEP-S5&tab=cp";
    const { fn, calls } = opsFetch();
    const { unmount } = render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sa-tab-cp")).toBeInTheDocument();
    expect(calls.some((c) => c.url === `${BASE}/products/BEP-S5?period=30d`)).toBe(true);
    unmount();
    search = "trang=xep-hang&kpi=ctr&src=live";
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sa-ranking")).toBeInTheDocument();
    expect(screen.getByTestId("sa-phan-tich")).toBeInTheDocument();
    // L1: the CTR table ranks by CTR, not by ₫ GMV/ngày
    await waitFor(() => expect(calls.some((c) => c.url.includes("/ranking?") && c.url.includes("source=live") && c.url.includes("xep_theo=ctr"))).toBe(true));
    await waitFor(() => expect(replaced.some((h) => h.includes("trang=phan-tich") && h.includes("kpi=ctr") && h.includes("src=live"))).toBe(true));
  });

  it("never asks a Shopee shop for the TikTok analysis (M4: it answered 404 'No analysis yet')", async () => {
    search = "trang=phan-tich";
    const { fn, calls } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("sa-phan-tich");
    await waitFor(() => expect(calls.some((c) => c.url.startsWith(`${BASE}/critical`))).toBe(true));
    expect(calls.some((c) => c.url.includes("/view/analysis"))).toBe(false);
  });

  it("still loads the TikTok analysis for a TikTok shop", async () => {
    const { fn, calls } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => VIEW_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("view-as-banner");
    await waitFor(() => expect(calls.some((c) => c.url.includes("/view/analysis"))).toBe(true));
  });

  it("a TikTok shop keeps Trang chủ / Quyết định / Phân tích / Juli / Quy tắc", async () => {
    const { fn } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => VIEW_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("view-as-banner");
    for (const name of ["Trang chủ", "Quyết định", "Phân tích", "Juli", "Quy tắc"]) {
      expect(await screen.findByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: "Sản phẩm" })).toBeNull();
  });
});

describe("Ops analytics tab (/ops/shops/{id}/shopee/phan-tich)", () => {
  it("adds 'Phân tích shop' to the Shopee dashboards and shows the four screens with an in-page tab strip", async () => {
    const { fn, calls } = opsFetch();
    render(<OpsShopeeAnalytics fetchImpl={fn} me={ME} shopId={SHOP_ID} />);
    expect(screen.getByRole("navigation", { name: "Dashboard Shopee" })).toHaveTextContent("Phân tích shop");
    await screen.findByTestId("sa-tile-gmv");
    const tabs = screen.getByTestId("sa-screen-tabs");
    for (const name of ["Tổng quan", "Phân tích", "Sản phẩm"]) expect(within(tabs).getByRole("link", { name })).toBeInTheDocument();
    expect(new URLSearchParams(within(tabs).getByRole("link", { name: "Phân tích" }).getAttribute("href")!.split("?")[1]).get("man")).toBe("phan-tich");
    expect(calls.some((c) => c.url === `${BASE}/channel-split?period=30d`)).toBe(true);
  });

  it("shows the screen named by ?man=", async () => {
    search = "man=phan-tich";
    const { fn } = opsFetch();
    render(<OpsShopeeAnalytics fetchImpl={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sa-phan-tich")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Phân tích" })).toHaveAttribute("aria-current", "page");
  });

  it("a TikTok shop gets the 409 refusal screen", async () => {
    const fn = vi.fn(async () => new Response(JSON.stringify({ detail: { code: "not_a_shopee_shop", message: "x" } }), { status: 409 })) as unknown as typeof fetch;
    render(<OpsShopeeAnalytics fetchImpl={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("sa-refusal-not-shopee")).toBeInTheDocument();
  });
});
