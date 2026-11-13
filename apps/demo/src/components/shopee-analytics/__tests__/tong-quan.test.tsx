import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { channelProducts, channelSplit, fakeApi } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { TongQuanView, aheadOfPace, findingOf, mil } from "../tong-quan";
import { params, renderWith } from "./harness";

const keys = () => screen.getAllByTestId(/^sa-channel-/).map((el) => el.getAttribute("data-testid")?.replace("sa-channel-", ""));

describe("Tổng quan (P100 board)", () => {
  it("header: shop, platform tag, last data time; Shop is the default level", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-fresh")).toHaveTextContent("Cập nhật 09/11/2026 09:30");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Shop gia dụng");
    expect(screen.getByTestId("sa-platform")).toHaveTextContent("Shopee");
    expect(within(screen.getByTestId("sa-level")).getByRole("button", { name: "Shop" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByTestId("sa-product-pick")).toBeNull();
  });

  it("the finding is number-led: each channel's share of GMV, no sentence", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-finding")).toHaveTextContent("Organic 28% GMV · Quảng cáo 63% · Tiếp thị liên kết 9%");
  });

  it("shop level rows: Organic (Thẻ sản phẩm, Shop), Quảng cáo (DVHT Sản phẩm, DVHT Shop+), Tiếp thị liên kết", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-channels");
    expect(keys()).toEqual(["organic", "organic_card", "organic_shop", "ads", "ads_product", "ads_shop", "affiliate"]);
    const organic = screen.getByTestId("sa-channel-organic");
    expect(organic).toHaveTextContent("3,61 tr đ");
    expect(organic).toHaveTextContent("14");
    const aff = screen.getByTestId("sa-channel-affiliate");
    expect(aff).toHaveTextContent("Tiếp thị liên kết");
    expect(aff).toHaveTextContent("10,0%"); // CTOR; Lượt xem and CTR are dashes
    expect(within(aff).getAllByText("—").length).toBeGreaterThanOrEqual(2);
  });

  it("names the ad base of each Quảng cáo figure and never mixes them", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-base-ads")).toHaveTextContent("Tổng quan lưu lượng");
    expect(screen.getByTestId("sa-base-ads_product")).toHaveTextContent("Báo cáo QC");
    expect(screen.getByTestId("sa-base-ads_shop")).toHaveTextContent("Báo cáo QC");
    expect(screen.getByTestId("sa-channel-ads")).toHaveTextContent("8,08 tr đ");
    expect(screen.getByTestId("sa-channel-ads_product")).toHaveTextContent("10,03 tr đ");
  });

  it("KPI tiles: GMV with đơn, Lợi nhuận, Chi phí quảng cáo, Chi phí tiếp thị liên kết", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-tile-gmv")).toHaveTextContent("12,89 tr đ");
    expect(screen.getByTestId("sa-tile-gmv")).toHaveTextContent("85 đơn");
    expect(screen.getByTestId("sa-tile-profit")).toHaveTextContent("2,10 tr đ");
    expect(screen.getByTestId("sa-tile-ads")).toHaveTextContent("2,57 tr đ");
    expect(screen.getByTestId("sa-tile-ads")).toHaveTextContent("Báo cáo QC");
    expect(screen.getByTestId("sa-tile-affiliate")).toHaveTextContent("96.000đ");
  });

  it("keeps the deep links: GMV tile and the Shop / Quảng cáo / Tiếp thị liên kết rows open Phân tích", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const tile = await screen.findByTestId("sa-tile-gmv");
    expect(tile.getAttribute("href")).toContain("/phan-tich");
    const link = within(screen.getByTestId("sa-channel-affiliate")).getByRole("link");
    expect(new URLSearchParams((link.getAttribute("href") ?? "").split("?")[1]).get("src")).toBe("lien_ket");
  });

  it("Sản phẩm level: picker, product-level rows, no Shop+ row", async () => {
    const api = fakeApi();
    renderWith(<TongQuanView params={params()} />, api);
    await screen.findByTestId("sa-channels");
    await userEvent.click(screen.getByRole("button", { name: "Sản phẩm" }));
    const pick = await screen.findByTestId("sa-product-pick");
    expect(within(pick).getAllByRole("option")).toHaveLength(2);
    await waitFor(() => expect(api.calls.some((c) => c.startsWith("channelSplit:") && c.includes('"productId":"1001"'))).toBe(true));
    await waitFor(() => expect(screen.queryByTestId("sa-channel-ads_shop")).toBeNull());
    expect(keys()).toEqual(["organic", "organic_card", "organic_shop", "ads", "affiliate"]);
    expect(screen.getByTestId("sa-base-ads")).toHaveTextContent("Báo cáo QC");
    expect(screen.getByTestId("sa-product-open").getAttribute("href")).toContain("1001");
    // the weakest metric of the chosen product is marked in the header
    expect(screen.getByText("CTR").getAttribute("data-weak")).toBe("true");
    await userEvent.selectOptions(pick, "1002");
    await waitFor(() => expect(api.calls.some((c) => c.includes('"productId":"1002"'))).toBe(true));
  });

  it("Kế hoạch toggle shows the month card: MTD vs goal, green when ahead of pace, today marker", async () => {
    // day 13/30 = 43 %: GMV 5 / 10 = 50 % (ahead), profit 0,7 / 3 = 23 % (behind)
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const card = await screen.findByTestId("sa-plan");
    expect(card).toHaveTextContent("Tháng 11");
    expect(card).toHaveTextContent("13/30 ngày");
    expect(screen.getByTestId("sa-plan-gmv")).toHaveTextContent("5,00 tr đ / 10,00 tr đ");
    expect(screen.getByTestId("sa-plan-gmv-fill").getAttribute("data-ahead")).toBe("true");
    expect(screen.getByTestId("sa-plan-profit-fill").getAttribute("data-ahead")).toBe("false");
    expect(screen.getByTestId("sa-plan-gmv-today").getAttribute("style")).toContain("43.33");
    await userEvent.click(screen.getByTestId("sa-plan-toggle"));
    expect(screen.queryByTestId("sa-plan")).toBeNull();
    expect(screen.getByTestId("sa-plan-toggle")).toHaveAttribute("aria-checked", "false");
  });

  it("with no goal the bar has no goal value and no explanation text", async () => {
    const base = channelSplit();
    renderWith(
      <TongQuanView params={params()} />,
      fakeApi({ split: { ...base, plan: { ...base.plan!, gmv: { now: 5_000_000, goal: null }, profit: { now: null, goal: null } } } }),
    );
    const gmv = await screen.findByTestId("sa-plan-gmv");
    expect(gmv).toHaveTextContent("5,00 tr đ");
    expect(gmv).not.toHaveTextContent("/");
    expect(screen.queryByTestId("sa-plan-gmv-fill")).toBeNull();
  });

  it("has no captions: no 'ước tính', no notices", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const page = await screen.findByTestId("sa-tong-quan");
    await screen.findByTestId("sa-channels");
    expect(page).not.toHaveTextContent(/ước tính|minh hoạ|tham khảo/i);
    expect(page.querySelector(".sa-notice")).toBeNull();
  });

  it("shows the refusal state when the API refuses", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({}, new ShopeeApiError(409, "no_shopee_data", "x")));
    expect(await screen.findByTestId("sa-refusal-no-data")).toBeInTheDocument();
  });
});

describe("Tổng quan helpers", () => {
  it("mil, finding and pace", () => {
    expect(mil(12_890_000)).toBe("12,89 tr đ");
    expect(mil(96_000)).toBe("96.000đ");
    expect(mil(null)).toBe("—");
    expect(findingOf(channelSplit())).toBe("Organic 28% GMV · Quảng cáo 63% · Tiếp thị liên kết 9%");
    expect(aheadOfPace({ now: 5, goal: 10 }, 13, 30)).toBe(true);
    expect(aheadOfPace({ now: 3, goal: 10 }, 13, 30)).toBe(false);
    expect(aheadOfPace({ now: 3, goal: null }, 13, 30)).toBe(false);
    expect(channelProducts().products[0]?.weakest_metric).toBe("ctr");
  });
});
