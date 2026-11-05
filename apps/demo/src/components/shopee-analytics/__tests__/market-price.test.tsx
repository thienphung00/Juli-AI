import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { barPercent, fetchMarketPrice, markerPosition, marketUrl, type MarketPrice } from "../../../lib/shopee-analytics/market-price";
import { MarketPriceBlock, MarketPriceView } from "../market-price-block";
import { MarketPriceMarker } from "../market-price-marker";

const ready: MarketPrice = {
  item_id: "1001",
  name: "Găng tay",
  available: true,
  reason: null,
  keyword: "găng tay cao su",
  collected_on: "2026-11-03",
  age_days: 2,
  stale: false,
  stale_after_days: 14,
  unit: { key: "hop", label: "hộp", per_label: "giá / hộp" },
  own: { variation_id: "", selling_price: 90000, price_min: 90000, price_max: 270000, pack_count: 1, price_per_unit: 90000 },
  market: { n_similar: 18, median: 82000, p25: 70000, p75: 95000, own_vs_median_pct: 9.8, position: "within" },
  closest: [1, 2, 3, 4, 5, 6].map((i) => ({ item_id: String(i), name: `SP tương tự ${i}`, shop_name: `Shop ${i}`, price: 80000 + i, price_min: null, price_max: null, pack_count: 1, price_per_unit: 80000 + i, sold_monthly: i === 2 ? null : 100 * i, sold_lifetime: 5000, position: i, is_ad: false })),
  marker: null,
  note: null,
};

const json = (body: unknown, status = 200) => vi.fn(async () => ({ ok: status < 300, status, json: async () => body }) as unknown as Response);

describe("Giá thị trường (P92 B-10)", () => {
  it("markerPosition and barPercent are pure and never guess", () => {
    expect(markerPosition(60000, { p25: 70000, p75: 95000 })).toBe("below_p25");
    expect(markerPosition(80000, { p25: 70000, p75: 95000 })).toBe("within");
    expect(markerPosition(99000, { p25: 70000, p75: 95000 })).toBe("above_p75");
    expect(markerPosition(null, { p25: 70000, p75: 95000 })).toBeNull();
    expect(markerPosition(80000, { p25: null, p75: 95000 })).toBeNull();
    expect(barPercent(5, 0, 10)).toBe(50);
    expect(barPercent(50, 0, 10)).toBe(100);
    expect(barPercent(5, 10, 10)).toBeNull();
  });

  it("builds the Demo and Ops urls (an Ops analytics base is accepted) and the lightweight builder one", () => {
    expect(marketUrl("/v1/demo/shopee", "1001")).toBe("/v1/demo/shopee/products/1001/market-price");
    expect(marketUrl("/v1/ops/shops/s1/shopee/analytics", "1001", { variationId: "v3", price: 88000.4 })).toBe("/v1/ops/shops/s1/shopee/products/1001/market-price?variation_id=v3&price=88000");
    expect(marketUrl("/v1/demo/shopee", "1001", { range: true, price: 88000 })).toBe("/v1/demo/shopee/builder/products/1001/market-range?price=88000");
  });

  it("shows unit, median, P25-P75, keyword, date and only the 5 closest listings", () => {
    render(<MarketPriceView data={ready} />);
    expect(screen.getByTestId("market-own")).toHaveTextContent("90.000đ");
    expect(screen.getByTestId("market-median")).toHaveTextContent("82.000đ");
    expect(screen.getByTestId("market-range")).toHaveTextContent("P25 70.000đ – P75 95.000đ (giá / hộp)");
    expect(screen.getByText("Từ khoá: găng tay cao su")).toBeInTheDocument();
    expect(screen.getByText("Thu thập 03/11/2026")).toBeInTheDocument();
    expect(screen.queryByText("cũ", { exact: false })).toBeNull();
    const rows = screen.getByTestId("market-closest").querySelectorAll("tbody tr");
    expect(rows).toHaveLength(5);
    expect(rows[1]).toHaveTextContent("—");
    expect(screen.getByTestId("market-bar-own")).toBeInTheDocument();
  });

  it("the seller's aggregate-only body shows median, average and count, and never a range, a bar or listings", () => {
    const seller: MarketPrice = {
      item_id: "1001",
      name: "Găng tay",
      available: true,
      reason: null,
      keyword: "găng tay cao su",
      collected_on: "2026-11-03",
      age_days: 2,
      stale: false,
      stale_after_days: 14,
      unit: ready.unit,
      own: ready.own,
      market: { n_similar: 18, median: 82000, average: 85500, own_vs_median_pct: 9.8, own_vs_average_pct: 5.3 },
      marker: null,
      note: null,
    };
    render(<MarketPriceView data={seller} />);
    expect(screen.getByTestId("market-median")).toHaveTextContent("82.000đ");
    expect(screen.getByTestId("market-average")).toHaveTextContent("85.500đ");
    expect(screen.getByTestId("market-average")).toHaveTextContent("+5,3% so với trung bình");
    expect(screen.getByText("18 sản phẩm tương tự")).toBeInTheDocument();
    expect(screen.queryByTestId("market-range")).toBeNull();
    expect(screen.queryByTestId("market-bar")).toBeNull();
    expect(screen.queryByTestId("market-closest")).toBeNull();
    expect(screen.queryByText(/P25|P75/)).toBeNull();
  });

  it("stale data keeps its date and gets the 'cũ' chip", () => {
    render(<MarketPriceView data={{ ...ready, stale: true, age_days: 20, collected_on: "2026-10-16" }} />);
    expect(screen.getByText("cũ · 20 ngày")).toBeInTheDocument();
    expect(screen.getByText("Thu thập 16/10/2026")).toBeInTheDocument();
  });

  it.each([
    ["no_keyword", "chưa có từ khoá chính"],
    ["no_capture", "Chưa đọc được trang tìm kiếm"],
    ["no_similar", "Chưa có sản phẩm tương tự"],
    ["market_closed", "Không đọc được dữ liệu thị trường"],
  ] as const)("absent data (%s) says why and shows no number", (reason, text) => {
    render(<MarketPriceView data={{ item_id: "1", available: false, reason, market: null, closest: null, marker: null }} />);
    expect(screen.getByTestId("market-absent")).toHaveTextContent(text);
    expect(screen.queryByTestId("market-median")).toBeNull();
  });

  it("the block loads through the scope's token and shop header", async () => {
    const fetchImpl = json(ready);
    render(<MarketPriceBlock itemId="1001" scope={{ base: "/v1/demo/shopee", token: "tok", shopId: "shop-1", fetchImpl }} />);
    expect(await screen.findByTestId("market-ready")).toBeInTheDocument();
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/v1/demo/shopee/products/1001/market-price");
    expect(init.headers).toMatchObject({ Authorization: "Bearer tok", "X-Shop-Id": "shop-1" });
  });

  it("a failed call says so instead of inventing numbers", async () => {
    const fetchImpl = json({ detail: { code: "x", message: "boom" } }, 500);
    render(<MarketPriceBlock itemId="1001" scope={{ base: "/v1/demo/shopee", token: "t", fetchImpl }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Chưa tải được giá thị trường");
    await expect(fetchMarketPrice({ base: "/v1/demo/shopee", token: "t", fetchImpl }, "1")).rejects.toThrow("boom");
  });

  it("the builder marker uses market-range with the drafted price and shows where it sits", async () => {
    const body: MarketPrice = { ...ready, closest: null, marker: { price: 99000, pack_count: 1, price_per_unit: 99000, position: "above_p75", vs_median_pct: 20.7 } };
    const fetchImpl = json(body);
    render(<MarketPriceMarker draftPrice={99000} itemId="1001" scope={{ base: "/v1/ops/shops/s1/shopee", token: "t", fetchImpl }} variationId="v3" />);
    const marker = await screen.findByTestId("market-marker");
    expect(marker).toHaveTextContent("trên khoảng phổ biến");
    expect(marker).toHaveTextContent("+20,7% so với trung vị");
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));
    expect((fetchImpl.mock.calls[0] as unknown as [string])[0]).toBe("/v1/ops/shops/s1/shopee/builder/products/1001/market-range?variation_id=v3&price=99000");
  });

  it("the builder marker with no capture shows the reason", async () => {
    const fetchImpl = json({ item_id: "1", available: false, reason: "no_capture", market: null, closest: null, marker: null });
    render(<MarketPriceMarker draftPrice={50000} itemId="1" scope={{ base: "/v1/demo/shopee", token: "t", fetchImpl }} />);
    expect(await screen.findByTestId("market-marker-absent")).toHaveTextContent("Chưa đọc được trang tìm kiếm");
  });
});
