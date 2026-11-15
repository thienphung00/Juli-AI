import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { fakeApi } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { ShopeeHostProvider } from "../../../lib/shopee-analytics/context";
import { sellerLinks } from "../../../lib/shopee-analytics/links";
import { stockFilterOf, stockText, type StockApi, type StockList, type StockRow } from "../../../lib/shopee-analytics/stock";
import { StockPanel } from "../stock-panel";
import { TongQuanView } from "../tong-quan";
import { UnsubscribeConfirm } from "../unsubscribe-confirm";
import { params } from "./harness";

const row = (over: Partial<StockRow> = {}): StockRow => ({
  key: "1001:11",
  item_id: "1001",
  model_id: "11",
  product_name: "Combo găng tay 100 hộp",
  variation_name: "Size M",
  sku_code: "GT-M",
  stock: 42,
  units_per_day: 6,
  days_left: 7,
  runs_out_on: "2026-11-22",
  out_of_stock: false,
  out_since: null,
  read_at: "2026-11-14T23:31:00Z",
  tracked: true,
  eligible: true,
  soon: true,
  ...over,
});

function fakeStock(list: StockList): StockApi & { calls: [string, boolean][] } {
  const calls: [string, boolean][] = [];
  return {
    calls,
    list: () => Promise.resolve(list),
    setTracked: (key, tracked) => {
      calls.push([key, tracked]);
      return Promise.resolve({ key, tracked });
    },
  };
}

function renderPanel(productId: string | null, keys: readonly string[], stock?: StockApi) {
  return render(
    <ShopeeHostProvider host={{ api: fakeApi(), links: sellerLinks, shopKey: "shop-1", shopName: "Shop", stock }}>
      <StockPanel keys={keys} productId={productId} />
    </ShopeeHostProvider>,
  );
}

function renderTq(q: string, stock?: StockApi) {
  return render(
    <ShopeeHostProvider host={{ api: fakeApi(), links: sellerLinks, shopKey: "shop-1", shopName: "Shop", stock }}>
      <TongQuanView params={params(q)} />
    </ShopeeHostProvider>,
  );
}

const LIST: StockList = {
  enabled: true,
  alert_days: 7,
  rows: [row(), row({ key: "1001:12", model_id: "12", variation_name: "Size L", sku_code: null, stock: 0, out_of_stock: true, runs_out_on: null, days_left: 0 }), row({ key: "1002", item_id: "1002", model_id: "", product_name: "Khăn giấy rút", variation_name: null, sku_code: null })],
};

describe("Sản phẩm: Theo dõi tồn kho (P100 Part S, owner 2026-11-15)", () => {
  it("texts: Còn n · hết khoảng dd/mm, Hết hàng, a dash without a read", () => {
    expect(stockText(row())).toBe("Còn 42 · hết khoảng 22/11");
    expect(stockText(row({ out_of_stock: true, stock: 0 }))).toBe("Hết hàng");
    expect(stockText(row({ stock: null }))).toBe("—");
    expect(stockFilterOf(params("ton_kho=1001:11,bad,1002"))).toEqual(["1001:11", "1002"]);
  });

  it("a product page: that product's variation rows, with the SKU code and the switch", async () => {
    const stock = fakeStock(LIST);
    renderPanel("1001", [], stock);
    expect(await screen.findByTestId("sa-stock-alert")).toHaveTextContent("Theo dõi tồn kho");
    const first = await screen.findByTestId("sa-stock-1001:11");
    expect(first).toHaveTextContent("Size M · SKU GT-M");
    expect(screen.getByTestId("sa-stock-left-1001:11")).toHaveTextContent("Còn 42 · hết khoảng 22/11");
    expect(screen.getByTestId("sa-stock-1001:12")).toHaveTextContent("Hết hàng");
    expect(screen.queryByTestId("sa-stock-1002")).toBeNull(); // another product
    expect(screen.getByTestId("sa-stock-track-1001:11")).toHaveAttribute("aria-checked", "true");
  });

  it("switching off asks first; Huỷ keeps it on, Ngừng theo dõi turns it off; on again needs no dialog", async () => {
    const user = userEvent.setup();
    const stock = fakeStock(LIST);
    renderPanel("1001", [], stock);
    const toggle = await screen.findByTestId("sa-stock-track-1001:11");
    await user.click(toggle);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveTextContent("Ngừng theo dõi SKU này?");
    expect(dialog).toHaveTextContent("Juli sẽ không gửi cảnh báo tồn kho và không tạo đề xuất cho SKU này.");
    await user.click(within(dialog).getByRole("button", { name: "Huỷ" }));
    expect(stock.calls).toEqual([]);
    await user.click(toggle);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Ngừng theo dõi" }));
    await waitFor(() => expect(screen.getByTestId("sa-stock-track-1001:11")).toHaveAttribute("aria-checked", "false"));
    await user.click(screen.getByTestId("sa-stock-track-1001:11"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await waitFor(() => expect(stock.calls).toEqual([["1001:11", false], ["1001:11", true]]));
  });

  it("the Sản phẩm list from the e-mail link: exactly its SKUs, each product name opening its page", async () => {
    renderPanel(null, stockFilterOf(params("ton_kho=1001:12,1002")), fakeStock(LIST));
    await screen.findByTestId("sa-stock-1002");
    expect(screen.getByTestId("sa-stock-1001:12")).toBeInTheDocument();
    expect(screen.queryByTestId("sa-stock-1001:11")).toBeNull();
    const name = within(screen.getByTestId("sa-stock-1002")).getByRole("link", { name: "Khăn giấy rút" });
    expect(name.getAttribute("href")).toContain("/san-pham/1002");
  });

  it("no stock API (Ops, reviewer) or a disabled list (sample shop): nothing", async () => {
    const { unmount } = renderPanel("1001", []);
    expect(screen.queryByTestId("sa-stock-alert")).toBeNull();
    unmount();
    renderPanel("1001", [], fakeStock({ enabled: false, rows: [] }));
    await waitFor(() => expect(screen.queryByTestId("sa-stock-alert")).toBeNull());
  });

  it("Tổng quan › Sản phẩm no longer carries the switch", async () => {
    renderTq("cap=san-pham&ton_kho=1001:11", fakeStock(LIST));
    await screen.findByTestId("sa-channels");
    expect(screen.queryByTestId("sa-stock-alert")).toBeNull();
    expect(screen.queryByTestId("sa-stock-track-1001:11")).toBeNull();
  });
});

describe("Huỷ nhận email (P100 Part S)", () => {
  it("opening the page changes nothing; the button posts the token once", async () => {
    const user = userEvent.setup();
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 200 })) as unknown as typeof fetch;
    render(<UnsubscribeConfirm fetchImpl={fetchImpl} token="tok.sig" />);
    expect(fetchImpl).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Huỷ nhận email này" }));
    expect(await screen.findByText("Đã huỷ nhận email báo cáo tồn kho")).toBeInTheDocument();
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = (fetchImpl as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0];
    expect(url).toBe("/v1/stock-alert/unsubscribe");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ token: "tok.sig" });
  });

  it("no token: an invalid-link page without a button", () => {
    render(<UnsubscribeConfirm token={null} />);
    expect(screen.getByText("Liên kết không hợp lệ")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
