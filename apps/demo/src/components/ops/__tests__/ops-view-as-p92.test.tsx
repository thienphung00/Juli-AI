import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { OpsViewAs } from "../ops-view-as";
import { ME, SETTINGS, SHOP_ID } from "./fixtures";
import { ADS, BOARD, FLOWS, ORDERS, PRODUCTS, PROMOS } from "./p92-dashboard-fixtures";

/** P92: Loại trừ sản phẩm in "Xem như shop" (read-only) and the settings area of Ops. */

vi.mock("recharts", async () => {
  const React = await import("react");
  const Box = ({ children }: { children?: React.ReactNode }) => React.createElement("div", null, children);
  return { ResponsiveContainer: Box, LineChart: Box, BarChart: Box, Bar: () => null, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null, Legend: () => null };
});

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  usePathname: () => "/ops",
  useSearchParams: () => new URLSearchParams(search),
}));

const SHOPEE_SESSION = { shop: { ...SETTINGS.shop, platform: "shopee" as const }, stage: "trial" as const, read_only: true as const };
const OPS = `/v1/ops/shops/${SHOP_ID}/shopee`;

beforeEach(() => {
  search = "";
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

describe("Xem như shop: Loại trừ sản phẩm", () => {
  it("is a nav entry on a Shopee shop and shows the list read-only through the Ops builder base", async () => {
    search = "trang=loai-tru";
    const calls: { url: string; method: string }[] = [];
    const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method ?? "GET" });
      if (url === `${OPS}/exclusions`) {
        return new Response(
          JSON.stringify({
            excluded: [{ item_id: "17820466113", name: "Bình giữ nhiệt inox X", reason: "ngung_ban", reason_label: "Ngừng bán", set_at: "2026-10-28T10:15:00+07:00" }],
            count: 1,
            reasons: [{ key: "ngung_ban", label: "Ngừng bán" }],
          }),
          { status: 200 },
        );
      }
      return new Response("{}", { status: 404 });
    }) as unknown as typeof fetch;
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("view-as-exclusions")).toBeInTheDocument();
    expect(await screen.findByTestId("sx-row-17820466113")).toHaveTextContent("Bình giữ nhiệt inox X");
    expect(screen.getByRole("button", { name: "Loại trừ" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByTestId("sx-add")).toBeNull();
    expect(screen.queryByRole("button", { name: "Hoàn tác" })).toBeNull();
    await waitFor(() => expect(calls.some((c) => c.url === `${OPS}/exclusions`)).toBe(true));
    expect(calls.every((c) => c.method === "GET")).toBe(true);
  });
});

describe("Xem như shop: the four pages from Ops (B-8)", () => {
  const route: Record<string, unknown> = {
    [`${OPS}/keywords`]: BOARD,
    [`${OPS}/products`]: PRODUCTS,
    [`${OPS}/flows`]: FLOWS,
    [`${OPS}/ads`]: ADS,
    [`${OPS}/promotions`]: PROMOS,
    [`${OPS}/orders`]: ORDERS,
  };
  function opsFetch() {
    const calls: { url: string; method: string; headers: Record<string, string> }[] = [];
    const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, method: init?.method ?? "GET", headers: Object.fromEntries(new Headers(init?.headers).entries()) });
      const body = route[url.split("?")[0]!];
      return body ? new Response(JSON.stringify(body), { status: 200 }) : new Response("{}", { status: 404 });
    }) as unknown as typeof fetch;
    return { fn, calls };
  }

  it("lists the four pages in the nav of a Shopee shop", async () => {
    const { fn } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    await screen.findByTestId("view-as-banner");
    for (const name of ["Từ khóa", "Dịch vụ hiển thị", "Đơn hàng", "Luồng"]) expect(await screen.findByRole("button", { name })).toBeInTheDocument();
  });

  it.each([
    ["tu-khoa", "keywords", "Từ khóa", `${OPS}/keywords`],
    ["quang-cao", "ads", "Dịch vụ hiển thị", `${OPS}/ads`],
    ["don-hang", "orders", "Đơn hàng", `${OPS}/orders`],
    ["luong-san-pham", "flows", "Luồng", `${OPS}/flows`],
  ])("trang=%s reads the Ops base (bearer only, GET only) and is read-only", async (slug, _tab, nav, path) => {
    search = `trang=${slug}`;
    const { fn, calls } = opsFetch();
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId(`dashboard-${slug}`)).toBeInTheDocument();
    await waitFor(() => expect(calls.some((c) => c.url.startsWith(path))).toBe(true));
    expect(screen.getByRole("button", { name: nav })).toHaveAttribute("aria-current", "page");
    for (const c of calls.filter((x) => x.url.startsWith("/v1/ops/shops/"))) {
      expect(c.method).toBe("GET");
      expect(c.headers.authorization).toBe("Bearer t");
      expect(c.headers["x-shop-id"]).toBeUndefined();
    }
    expect(calls.every((c) => !c.url.startsWith("/v1/demo"))).toBe(true);
    // The page's own tab strip stays inside the view-as page.
    const hrefs = within(screen.getByTestId("dashboard-tabs")).getAllByRole("link").map((a) => a.getAttribute("href"));
    expect(hrefs.every((h) => h!.startsWith(`/ops/shops/${SHOP_ID}/xem?trang=`))).toBe(true);
  });

  it("the keywords page has no writes in view-as, and the orders page shows only the hashed key", async () => {
    search = "trang=tu-khoa";
    const { fn } = opsFetch();
    const first = render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    await screen.findByRole("table", { name: "Từ khóa" });
    expect(screen.queryByRole("button", { name: /Tạo từ khóa/ })).toBeNull();
    first.unmount();
    search = "trang=don-hang";
    render(<OpsViewAs api={{ viewSession: async () => SHOPEE_SESSION }} baseFetch={fn} me={ME} shopId={SHOP_ID} />);
    expect(await screen.findByTestId("order-0000000000a1")).toHaveTextContent("0000000000a1");
    expect(screen.getByTestId("orders-privacy")).toHaveTextContent("không có thông tin người mua");
  });
});
