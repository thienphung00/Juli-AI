import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import type { ShopeeAds, ShopeeFlows, ShopeeProducts, ShopeePromotions } from "../../../lib/ops/types";
import { OpsShopeeAds } from "../shopee/ops-shopee-ads";
import { OpsShopeeProducts } from "../shopee/ops-shopee-products";
import { ME, SHOP_ID } from "./fixtures";

/** ADR-117 step 4: the two Shopee dashboards, with synthetic numbers only. */

vi.mock("recharts", async () => {
  const React = await import("react");
  const Box = ({ children }: { children?: React.ReactNode }) => React.createElement("div", null, children);
  return {
    ResponsiveContainer: Box,
    BarChart: Box,
    LineChart: Box,
    Bar: () => null,
    Line: () => null,
    CartesianGrid: () => null,
    XAxis: () => null,
    YAxis: () => null,
    Tooltip: () => null,
    Legend: () => null,
  };
});
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("../ops-cost-banner", () => ({ OpsCostBanner: () => null }));

const RANGE = { from: "2026-10-01", to: "2026-10-30" };
const cell = { orders: 10, impressions: 1000, clicks: 50, buyers: 8 };

const FLOWS: ShopeeFlows = {
  range: RANGE,
  order_type: "confirmed",
  total_gmv: 1_200_000,
  total_orders: 12,
  flows: [
    {
      stream: "product_card",
      label: "Thẻ sản phẩm",
      gmv: 1_000_000,
      ...cell,
      has_total_row: true,
      children: [{ segment: "shop_page", label: "Trang shop", gmv: 300_000, ...cell }],
    },
    { stream: "seller_video", label: "Video", gmv: 200_000, ...cell, has_total_row: true, children: [] },
  ],
  ads_overlay: { stream: "ads", label: "Dịch vụ Hiển thị", gmv: 90_000, orders: 2, in_total: false },
  monthly: [{ month: "2026-10-01", streams: { product_card: 1_000_000, seller_video: 200_000 }, shop_page_gmv: 300_000 }],
  shop_monthly: [{ month: "2026-10-01", gmv: 1_200_000, orders: 12 }],
  has_data: true,
};

const FUNNEL = { impressions: 1000, clicks: 50, visitors: 40, page_views: 90, add_to_cart: 10, orders: 5, gmv: 800_000, units: 6, buyers: 4, ctr: 0.05, add_to_cart_rate: 0.25, click_to_order: 0.1 };
const PRODUCTS: ShopeeProducts = {
  order_type: "confirmed",
  period: { from: "2026-09-29", to: "2026-10-28" },
  periods: [
    { from: "2026-09-29", to: "2026-10-28", items: 2 },
    { from: "2026-10-01", to: "2026-10-28", items: 2 },
  ],
  items_total: 2,
  totals: FUNNEL,
  products: [
    {
      item_id: "111",
      name: "Sản phẩm thử",
      ...FUNNEL,
      by_flow: { product_card: { gmv: 600_000, orders: 4 } },
      history: [{ month: "2026-10-01", gmv: 800_000, orders: 5 }],
      flags: [{ flag: "ads_optimize", label: "Nên tối ưu quảng cáo", from: "2026-10-01", to: "2026-10-28" }],
    },
  ],
  shop_monthly: [],
  has_data: true,
};

const AD = (ad_type: string, label: string, cost: number, gmv: number, orders: number) => ({
  ad_type,
  label,
  cost,
  gmv,
  orders,
  roas: gmv / cost,
  cost_per_order: cost / orders,
});
const ADS: ShopeeAds = {
  range: RANGE,
  order_type: "placed",
  total: { cost: 600_000, gmv: 720_000, orders: 12, roas: 1.2, cost_per_order: 50_000 },
  by_type: [AD("ads_auto_bid", "GMV tối đa tự động đấu thầu", 600_000, 720_000, 12)],
  daily: [{ day: "2026-10-01", by_type: [AD("ads_auto_bid", "x", 100_000, 120_000, 2)] }],
  monthly: [{ month: "2026-10-01", cost: 600_000, gmv: 720_000, orders: 12, roas: 1.2, cost_per_order: 50_000, by_type: [AD("ads_auto_bid", "x", 600_000, 720_000, 12)] }],
  campaigns: [],
  campaigns_available: false,
  alerts: [{ ad_type: "ads_auto_bid", label: "GMV tối đa tự động đấu thầu", days: 6, from: "2026-10-01", to: "2026-10-06", roas: 1.2, floor: 1.5 }],
  alert_rule: { floor: 1.5, min_days: 5 },
  has_data: true,
};
const PROMOS: ShopeePromotions = {
  range: RANGE,
  order_type: "confirmed",
  programs: [{ promo_type: "discount", type_label: "Khuyến mãi", name: "Chương trình thử", starts_at: "2026-10-02T00:00:00", ends_at: "2026-10-05T00:00:00", status: "Đã kết thúc", gmv: 700_000, orders: 7, units: 9, buyers: 6 }],
  daily: [],
  has_data: true,
};

describe("Sản phẩm + luồng", () => {
  it("shows Trang shop as a child row and keeps it out of the total", async () => {
    const api = { shopeeFlows: vi.fn().mockResolvedValue(FLOWS), shopeeProducts: vi.fn().mockResolvedValue(PRODUCTS) };
    render(<OpsShopeeProducts api={api} me={ME} shopId={SHOP_ID} />);
    const child = await screen.findByTestId("child-product_card-shop_page");
    expect(child).toHaveTextContent("Trang shop");
    expect(child).toHaveTextContent("300.000");
    const table = screen.getByRole("table", { name: "GMV theo luồng" });
    // the total row is the two level-1 flows (1.000.000 + 200.000), not + 300.000
    expect(within(table).getByText("Tổng các luồng").closest("tr")).toHaveTextContent("1.200.000");
    expect(screen.getByTestId("ads-overlay")).toHaveTextContent("không cộng vào tổng");
  });

  it("renders the funnel, flags and the per-product detail", async () => {
    const api = { shopeeFlows: vi.fn().mockResolvedValue(FLOWS), shopeeProducts: vi.fn().mockResolvedValue(PRODUCTS) };
    render(<OpsShopeeProducts api={api} me={ME} shopId={SHOP_ID} />);
    const row = (await screen.findByText(/Sản phẩm thử/)).closest("tr")!;
    expect(row).toHaveTextContent("5,00 %");
    expect(row).toHaveTextContent("10,00 %");
    expect(row).toHaveTextContent("Nên tối ưu quảng cáo");
    fireEvent.click(screen.getByRole("button", { name: /Sản phẩm thử/ }));
    expect(screen.getByText("Lịch sử 12 tháng")).toBeInTheDocument();
    expect(screen.getByText(/10\/2026: 800.000/)).toBeInTheDocument();
  });

  it("shows giá (min-max, list struck) and biên with its basis on every funnel row (P92 B-9)", async () => {
    const withPrice = {
      ...PRODUCTS,
      products: [{ ...PRODUCTS.products[0]!, price_min: 54_000, price_max: 54_000, list_price: 60_000, price_basis: "order_lines", margin_pct: 16.3, margin_basis: "theo đơn thực tế" }, { ...PRODUCTS.products[0]!, item_id: "222", name: "Không có đơn", price_min: null, price_max: null, list_price: null, margin_pct: null, margin_basis: "chưa tính" }],
    };
    const api = { shopeeFlows: vi.fn().mockResolvedValue(FLOWS), shopeeProducts: vi.fn().mockResolvedValue(withPrice) };
    render(<OpsShopeeProducts api={api} me={ME} shopId={SHOP_ID} />);
    const price = await screen.findByTestId("price-111");
    expect(price).toHaveTextContent(/54\.000/);
    expect(price.querySelector("s")).toHaveTextContent(/60\.000/);
    expect(screen.getByTestId("margin-111")).toHaveTextContent("16,3%");
    expect(screen.getByTestId("margin-111")).toHaveTextContent("theo đơn thực tế");
    expect(screen.getByTestId("price-222")).toHaveTextContent("—");
    expect(screen.getByTestId("margin-222")).toHaveTextContent("chưa tính");
  });

  it("asks again with the chosen order type and period", async () => {
    const api = { shopeeFlows: vi.fn().mockResolvedValue(FLOWS), shopeeProducts: vi.fn().mockResolvedValue(PRODUCTS) };
    render(<OpsShopeeProducts api={api} me={ME} shopId={SHOP_ID} />);
    await screen.findByText("Phễu theo sản phẩm");
    fireEvent.change(screen.getByLabelText("Kỳ báo cáo"), { target: { value: "2026-10-01|2026-10-28" } });
    await waitFor(() => expect(api.shopeeProducts).toHaveBeenLastCalledWith(SHOP_ID, { orderType: "confirmed", periodFrom: "2026-10-01", periodTo: "2026-10-28" }));
    fireEvent.change(screen.getByLabelText("Loại đơn hàng"), { target: { value: "placed" } });
    await waitFor(() => expect(api.shopeeFlows).toHaveBeenLastCalledWith(SHOP_ID, expect.objectContaining({ orderType: "placed" })));
  });

  it("says so when there is no data yet", async () => {
    const api = {
      shopeeFlows: vi.fn().mockResolvedValue({ ...FLOWS, flows: [], has_data: false, monthly: [], shop_monthly: [] }),
      shopeeProducts: vi.fn().mockResolvedValue({ ...PRODUCTS, products: [], totals: null, periods: [], period: null, has_data: false }),
    };
    render(<OpsShopeeProducts api={api} me={ME} shopId={SHOP_ID} />);
    const empties = await screen.findAllByTestId("shopee-empty");
    expect(empties).toHaveLength(2);
    expect(empties[0]).toHaveTextContent("Chưa có dữ liệu luồng truy cập");
  });

  it("says a TikTok shop is not a Shopee shop", async () => {
    const api = { shopeeFlows: vi.fn().mockRejectedValue(new OpsApiError(409, "x")), shopeeProducts: vi.fn().mockRejectedValue(new OpsApiError(409, "x")) };
    render(<OpsShopeeProducts api={api} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("không phải shop Shopee");
  });
});

describe("Quảng cáo + khuyến mãi", () => {
  it("lists cost, orders, ROAS and cost per order by ad type, with the low-ROAS alert", async () => {
    const api = { shopeeAds: vi.fn().mockResolvedValue(ADS), shopeePromotions: vi.fn().mockResolvedValue(PROMOS) };
    render(<OpsShopeeAds api={api} me={ME} shopId={SHOP_ID} />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("ROAS 1,20 thấp hơn 1,50 trong 6 ngày liên tục");
    const row = screen.getByRole("table", { name: "Quảng cáo theo loại" }).querySelector("tbody tr")!;
    expect(row).toHaveTextContent("600.000");
    expect(row).toHaveTextContent("1,20");
    expect(row).toHaveTextContent("50.000");
    expect(screen.getByTestId("ads-total")).toHaveTextContent("720.000");
  });

  it("shows the campaign empty state and the promotion timeline", async () => {
    const api = { shopeeAds: vi.fn().mockResolvedValue({ ...ADS, alerts: [] }), shopeePromotions: vi.fn().mockResolvedValue(PROMOS) };
    render(<OpsShopeeAds api={api} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByText(/Chưa có dữ liệu theo chiến dịch/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    const timeline = screen.getByRole("list", { name: "Dòng thời gian khuyến mãi" });
    expect(timeline).toHaveTextContent("Chương trình thử");
    expect(timeline).toHaveTextContent("700.000");
  });

  it("shows empty states without data", async () => {
    const api = {
      shopeeAds: vi.fn().mockResolvedValue({ ...ADS, by_type: [], daily: [], monthly: [], alerts: [], has_data: false }),
      shopeePromotions: vi.fn().mockResolvedValue({ ...PROMOS, programs: [], has_data: false }),
    };
    render(<OpsShopeeAds api={api} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByText("Chưa có dữ liệu quảng cáo cho khoảng ngày này.")).toBeInTheDocument();
    expect(screen.getByText(/Không có chương trình khuyến mãi/)).toBeInTheDocument();
  });

  it("refuses a range the server rejects", async () => {
    const api = { shopeeAds: vi.fn().mockRejectedValue(new OpsApiError(422, "x")), shopeePromotions: vi.fn().mockResolvedValue(PROMOS) };
    render(<OpsShopeeAds api={api} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Khoảng ngày không hợp lệ");
  });
});
