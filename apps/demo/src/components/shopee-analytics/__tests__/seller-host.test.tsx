import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { channelProducts, channelSplit, critical, kolSection, matrix, metricView, overview, product, ranking } from "../../../lib/shopee-analytics/__tests__/fixtures";
import type { ShopReportState } from "../../../lib/shop-report/shop-report-context";
import { SellerShopeePage, SellerShopeeProductPage } from "../hosts";

let state: ShopReportState = { status: "resolving" };
let search = "";
vi.mock("../../../lib/shop-report/shop-report-context", () => ({
  useShopReport: () => ({ state, reload: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  useParams: () => ({ itemId: "BEP-S5" }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

const calls: { url: string; headers: Record<string, string> }[] = [];
beforeEach(() => {
  calls.length = 0;
  search = "";
  state = { status: "ready", token: "tok", shop: { id: "shop-9", name: "Shop gia dụng" }, envelope: {} as never };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, headers: Object.fromEntries(new Headers(init?.headers).entries()) });
      const path = url.split("?")[0]!;
      const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });
      if (path.endsWith("/overview")) return json(overview());
      if (path.endsWith("/channel-split/products")) return json(channelProducts());
      if (path.endsWith("/channel-split")) return json(channelSplit());
      if (path.endsWith("/matrix")) return json(matrix());
      if (path.endsWith("/critical")) return json(critical());
      if (path.endsWith("/ranking")) return json(ranking());
      if (path.endsWith("/metric-view")) return json(metricView());
      if (path.endsWith("/kol-section")) return json(kolSection());
      if (path.includes("/products/")) return json(product());
      return new Response("{}", { status: 404 });
    }),
  );
});

describe("the seller routes of the Shopee screens", () => {
  it("/tong-quan reads the seller API with bearer and X-Shop-Id", async () => {
    render(<SellerShopeePage screen="tong-quan" />);
    expect(await screen.findByTestId("sa-tile-gmv")).toBeInTheDocument();
    const first = calls.find((c) => c.url.startsWith("/v1/demo/shopee/channel-split?"))!;
    expect(first.url).toBe("/v1/demo/shopee/channel-split?period=30d");
    expect(first.headers.authorization).toBe("Bearer tok");
    expect(first.headers["x-shop-id"]).toBe("shop-9");
  });

  it("/phan-tich (metric view, KOL section), /san-pham and /san-pham/[itemId]", async () => {
    const { unmount } = render(<SellerShopeePage screen="phan-tich" />);
    expect(await screen.findByTestId("sa-phan-tich")).toBeInTheDocument();
    unmount();
    // P96b: what was /xep-hang is Phân tích's product table (next.config redirects /xep-hang here)
    search = "kpi=ctr&src=live";
    const r = render(<SellerShopeePage screen="phan-tich" />);
    expect(await screen.findByTestId("pt-products")).toBeInTheDocument();
    expect(screen.getByTestId("sa-phan-tich")).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.includes("/metric-view?") && c.url.includes("metric=ctr") && c.url.includes("channel=live"))).toBe(true));
    expect(calls.some((c) => c.url.startsWith("/v1/demo/shopee/kol-section"))).toBe(true);
    r.unmount();
    const l = render(<SellerShopeePage screen="san-pham" />);
    expect(await screen.findByTestId("sa-product-list")).toBeInTheDocument();
    l.unmount();
    render(<SellerShopeeProductPage />);
    expect(await screen.findByTestId("sa-san-pham")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/v1/demo/shopee/products/BEP-S5?period=30d")).toBe(true);
  });

  it("carries the window in the URL to the API", async () => {
    search = "ky=7d";
    render(<SellerShopeePage screen="tong-quan" />);
    await screen.findByTestId("sa-tile-gmv");
    expect(calls.some((c) => c.url === "/v1/demo/shopee/channel-split?period=7d")).toBe(true);
  });

  it("without a signed-in shop it asks for one and calls nothing", async () => {
    state = { status: "anonymous", envelope: null };
    render(<SellerShopeePage screen="tong-quan" />);
    expect(await screen.findByTestId("sa-needs-shop")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("while the session resolves it only says it is loading", () => {
    state = { status: "resolving" };
    render(<SellerShopeePage screen="tong-quan" />);
    expect(screen.getByText("Đang tải…")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });
});
