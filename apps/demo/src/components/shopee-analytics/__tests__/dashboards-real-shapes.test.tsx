import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ShopReportState } from "../../../lib/shop-report/shop-report-context";
import real from "../../ops/__tests__/fixtures/p92-real-responses.json";
import { SellerDashboardPage } from "../dashboard-pages";

/**
 * P92 B-8 / B-9: the seller's four Ops pages parse the answers of the REAL serializers.
 * `p92-real-responses.json` is written and guarded by tests/integration/test_demo_shopee_pages_db.py
 * (Postgres, the real Demo routes, a synthetic shop), never by hand.
 */

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

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200 });

beforeEach(() => {
  state = { status: "ready", token: "tok", shop: { id: "shop-9", name: "Shop gia dụng" }, envelope: {} as never };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input).split("?")[0]!;
      if (path === "/v1/demo/shopee/keywords") return json(real.keywords);
      if (path === "/v1/demo/shopee/dashboard/products") return json(real.products);
      if (path === "/v1/demo/shopee/dashboard/flows") return json(real.flows);
      if (path === "/v1/demo/shopee/dashboard/ads") return json(real.ads);
      if (path === "/v1/demo/shopee/dashboard/promotions") return json(real.promotions);
      if (path === "/v1/demo/shopee/orders") return json(real.orders);
      return new Response("{}", { status: 404 });
    }),
  );
});

describe("the seller's Demo pages parse the real answers", () => {
  it("Từ khóa: the keyword rows, coverage and the per-product status", async () => {
    render(<SellerDashboardPage kind="tu-khoa" />);
    const table = await screen.findByRole("table", { name: "Từ khóa" });
    expect(table).toHaveTextContent("găng tay tự hủy");
    expect(table).toHaveTextContent("300");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Đơn hàng: every order row, the status counts and no buyer data", async () => {
    const { container } = render(<SellerDashboardPage kind="don-hang" />);
    const rows = await screen.findAllByTestId(/^order-/);
    expect(rows).toHaveLength(real.orders.orders.length);
    expect(screen.getByTestId("orders-by-status")).toHaveTextContent("12 đã giao");
    expect(screen.getByTestId("orders-by-status")).toHaveTextContent("1 đã hủy");
    expect(screen.getByTestId("orders-privacy")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(container.textContent).not.toMatch(/số điện thoại|địa chỉ giao/i);
  });

  it("Sản phẩm + luồng: the funnel rows carry giá (list struck) and biên with its basis from the same answer", async () => {
    render(<SellerDashboardPage kind="luong-san-pham" />);
    const first = real.products.products[0]!;
    const row = (await screen.findByText(new RegExp(first.name!))).closest("tr")!;
    expect(row).toHaveTextContent("85.000");
    expect(within(row).getByTestId(`price-${first.item_id}`)).toHaveTextContent("85.000");
    expect(within(row).getByTestId(`price-${first.item_id}`)).toHaveTextContent(/85\.000.*–.*100\.000/);
    // 1002 sold at 54.000 against a list price of 60.000: the list price is struck through.
    const second = real.products.products[1]!;
    const struck = within(screen.getByTestId(`price-${second.item_id}`)).getByText(/60\.000/);
    expect(struck.tagName).toBe("S");
    expect(within(row).getByTestId(`margin-${first.item_id}`)).toHaveTextContent(first.margin_basis);
    expect(within(row).getByTestId(`margin-${first.item_id}`)).toHaveTextContent("42,5%");
    expect(screen.getAllByText("GMV theo luồng").length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("Quảng cáo + khuyến mãi: the totals and the programmes", async () => {
    render(<SellerDashboardPage kind="quang-cao" />);
    expect(await screen.findByTestId("ads-total")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
