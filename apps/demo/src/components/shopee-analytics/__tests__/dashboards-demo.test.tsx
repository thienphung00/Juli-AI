import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ADS, BOARD, FLOWS, ORDERS, PRODUCTS, PROMOS } from "../../ops/__tests__/p92-dashboard-fixtures";
import type { ShopReportState } from "../../../lib/shop-report/shop-report-context";
import { createDashboardsApi, DEMO_DASHBOARDS_BASE, opsDashboardsBase } from "../../../lib/shopee-analytics/dashboards-client";
import { SellerDashboardPage } from "../dashboard-pages";

/** P92 B-8: the four Ops pages as the seller's read-only Demo pages. */

vi.mock("recharts", async () => {
  const React = await import("react");
  const Box = ({ children }: { children?: React.ReactNode }) => React.createElement("div", null, children);
  return { ResponsiveContainer: Box, LineChart: Box, BarChart: Box, Bar: () => null, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Legend: () => null };
});
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

let state: ShopReportState = { status: "resolving" };
vi.mock("../../../lib/shop-report/shop-report-context", () => ({
  useShopReport: () => ({ state, reload: vi.fn() }),
}));

const calls: { url: string; method: string; headers: Record<string, string> }[] = [];
const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });

beforeEach(() => {
  calls.length = 0;
  state = { status: "ready", token: "tok", shop: { id: "shop-9", name: "Shop gia dụng" }, envelope: {} as never };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method ?? "GET", headers: Object.fromEntries(new Headers(init?.headers).entries()) });
      const path = url.split("?")[0]!;
      if (path === "/v1/demo/shopee/keywords") return json(BOARD);
      if (path === "/v1/demo/shopee/dashboard/products") return json(PRODUCTS);
      if (path === "/v1/demo/shopee/dashboard/flows") return json(FLOWS);
      if (path === "/v1/demo/shopee/dashboard/ads") return json(ADS);
      if (path === "/v1/demo/shopee/dashboard/promotions") return json(PROMOS);
      if (path === "/v1/demo/shopee/orders") return json(ORDERS);
      return new Response("{}", { status: 404 });
    }),
  );
});

function expectSeller(pathPrefix: string) {
  const mine = calls.filter((c) => c.url.startsWith(pathPrefix));
  expect(mine.length).toBeGreaterThan(0);
  for (const c of mine) {
    expect(c.method).toBe("GET");
    expect(c.headers.authorization).toBe("Bearer tok");
    expect(c.headers["x-shop-id"]).toBe("shop-9");
  }
}

describe("the seller's Demo pages from Ops", () => {
  it("Từ khóa reads /keywords and offers no write", async () => {
    render(<SellerDashboardPage kind="tu-khoa" />);
    expect(await screen.findByRole("table", { name: "Từ khóa" })).toHaveTextContent("nước rửa chén");
    expectSeller("/v1/demo/shopee/keywords");
    expect(screen.queryByRole("button", { name: /Tạo từ khóa từ tiêu đề/ })).toBeNull();
    expect(screen.queryByLabelText(/Tải lên kết quả tra cứu/)).toBeNull();
    expect(screen.queryByLabelText(/Giữ từ khóa/)).toBeNull();
    expect(screen.queryByLabelText("Danh sách cần tra")).toBeNull();
    expect(screen.getByTestId("dashboard-tu-khoa")).not.toHaveTextContent("Chỉ xem");
  });

  it("Quảng cáo + khuyến mãi reads /dashboard/ads and /dashboard/promotions", async () => {
    render(<SellerDashboardPage kind="quang-cao" />);
    expect(await screen.findByTestId("ads-total")).toHaveTextContent("600.000");
    expect(await screen.findByText("Chương trình thử")).toBeInTheDocument();
    expectSeller("/v1/demo/shopee/dashboard/ads");
    expectSeller("/v1/demo/shopee/dashboard/promotions");
  });

  it("Sản phẩm + luồng reads /dashboard/flows and /dashboard/products", async () => {
    render(<SellerDashboardPage kind="luong-san-pham" />);
    expect(await screen.findByTestId("child-product_card-shop_page")).toHaveTextContent("Trang shop");
    expect(await screen.findByText(/Sản phẩm thử/)).toBeInTheDocument();
    expectSeller("/v1/demo/shopee/dashboard/flows");
    expectSeller("/v1/demo/shopee/dashboard/products");
  });

  it("Đơn hàng reads /orders, shows only the hashed key and no buyer data", async () => {
    const { container } = render(<SellerDashboardPage kind="don-hang" />);
    const row = await screen.findByTestId("order-0000000000a1");
    expect(row).toHaveTextContent("0000000000a1");
    expect(row).toHaveTextContent("Đã giao");
    expect(row).toHaveTextContent("Voucher");
    expect(row).toHaveTextContent("38.000");
    expect(screen.getByTestId("order-0000000000b2")).toHaveTextContent("Đã hủy");
    expect(screen.getByTestId("orders-privacy")).toHaveTextContent("không có thông tin người mua");
    expect(container.textContent).not.toMatch(/người mua:|số điện thoại|địa chỉ giao/i);
    expect(screen.getByTestId("orders-by-status")).toHaveTextContent("1 đã giao");
    expectSeller("/v1/demo/shopee/orders");
    expect(calls.find((c) => c.url.startsWith("/v1/demo/shopee/orders"))!.url).toContain("period=30d");
    // A filter goes to the API.
    await userEvent.selectOptions(screen.getByLabelText("Trạng thái"), "cancelled");
    await waitFor(() => expect(calls.some((c) => c.url.includes("/orders") && c.url.includes("status=cancelled"))).toBe(true));
  });

  it("links the five Dữ liệu shop sub-tabs to each other on the seller routes", async () => {
    render(<SellerDashboardPage kind="tu-khoa" />);
    const tabs = await screen.findByTestId("dashboard-tabs");
    const hrefs = within(tabs).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs).toEqual(["/san-pham", "/tu-khoa", "/quang-cao", "/don-hang", "/luong-san-pham"]);
    expect(within(tabs).getByRole("link", { name: "Từ khóa" })).toHaveAttribute("aria-current", "page");
  });

  it("without a signed-in shop it asks for one and calls nothing", async () => {
    state = { status: "anonymous", envelope: null };
    render(<SellerDashboardPage kind="don-hang" />);
    expect(await screen.findByTestId("sa-needs-shop")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("a TikTok shop (409) gets the refusal, not an empty table", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: { code: "not_a_shopee_shop", message: "x" } }), { status: 409 })));
    render(<SellerDashboardPage kind="quang-cao" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("không phải shop Shopee");
  });
});

describe("the dashboards client", () => {
  it("builds the demo paths with the dashboard prefix and the Ops paths without it", async () => {
    const seen: string[] = [];
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      seen.push(String(input));
      return json({});
    }) as unknown as typeof fetch;
    const demo = createDashboardsApi({ base: DEMO_DASHBOARDS_BASE, dashboardPrefix: "/dashboard", token: "t", shopId: "s", fetchImpl });
    const ops = createDashboardsApi({ base: opsDashboardsBase("sh 1"), dashboardPrefix: "", token: "t", fetchImpl });
    await demo.shopeeProducts("x", { orderType: "confirmed", periodFrom: "2026-09-01", periodTo: "2026-09-30" });
    await demo.shopeeFlows("x", { from: "2026-10-01", to: "2026-10-30" });
    await demo.shopeeKeywords("x", 150);
    await ops.shopeeAds("x", { orderType: "placed" });
    await ops.shopeePromotions("x");
    await ops.shopeeOrders("x", { period: "7d", lever: "combo", sort: "gmv", limit: 100, offset: 100 });
    expect(seen).toEqual([
      "/v1/demo/shopee/dashboard/products?order_type=confirmed&period_from=2026-09-01&period_to=2026-09-30",
      "/v1/demo/shopee/dashboard/flows?from=2026-10-01&to=2026-10-30",
      "/v1/demo/shopee/keywords?min_volume=150",
      "/v1/ops/shops/sh%201/shopee/ads?order_type=placed",
      "/v1/ops/shops/sh%201/shopee/promotions",
      "/v1/ops/shops/sh%201/shopee/orders?period=7d&lever=combo&sort=gmv&limit=100&offset=100",
    ]);
  });
});
