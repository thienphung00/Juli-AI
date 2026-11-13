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

  it("the finding is number-led: GMV and CTR Thẻ sản phẩm change vs the previous period", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-finding")).toHaveTextContent("GMV ▲ 17 % · CTR Thẻ sản phẩm ▼ 9,4 %");
  });

  it("shop level rows: Organic (Thẻ sản phẩm, Trang shop, Video, Live), Quảng cáo (DVHT Sản phẩm, DVHT Shop+), Tiếp thị liên kết", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-channels");
    expect(keys()).toEqual(["organic", "organic_card", "organic_shop", "organic_video", "organic_live", "ads", "ads_product", "ads_shop", "affiliate"]);
    const organic = screen.getByTestId("sa-channel-organic");
    expect(organic).toHaveTextContent("3,61 tr đ");
    expect(organic).toHaveTextContent("28,0%"); // % GMV
    const aff = screen.getByTestId("sa-channel-affiliate");
    expect(aff).toHaveTextContent("Tiếp thị liên kết");
    expect(aff).toHaveTextContent("10,0%"); // CTOR; Lượt xem and CTR are dashes
    expect(within(aff).getAllByText("—").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByTestId("sa-cell-ads_product-share")).toHaveTextContent("—"); // ads-report base: no share
  });

  it("each cell shows its change vs the previous period under the value", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-cell-organic-gmv")).toHaveTextContent("▲ 20 %"); // 3,61 vs 3,0 tr
    expect(screen.getByTestId("sa-cell-organic_card-ctr")).toHaveTextContent("▼ 9,4 %");
    expect(screen.getByTestId("sa-cell-organic_shop-gmv").textContent).not.toMatch(/[▲▼]/); // no previous data
  });

  it("names the ad base of each Quảng cáo figure and never mixes them", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-base-ads")).toHaveTextContent("Tổng quan lưu lượng");
    expect(screen.getByTestId("sa-base-ads_product")).toHaveTextContent("Báo cáo DVHT");
    expect(screen.getByTestId("sa-base-ads_shop")).toHaveTextContent("Báo cáo DVHT");
    expect(screen.getByTestId("sa-channel-ads")).toHaveTextContent("8,08 tr đ");
    expect(screen.getByTestId("sa-channel-ads_product")).toHaveTextContent("10,03 tr đ");
  });

  it("KPI tiles: GMV, Lợi nhuận, Tổng chi phí with its three lines, ROI in points; each with its change", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-tile-gmv")).toHaveTextContent("12,89 tr đ");
    expect(screen.getByTestId("sa-shift-gmv")).toHaveTextContent("▲ 17 %");
    expect(screen.getByTestId("sa-tile-profit")).toHaveTextContent("2,70 tr đ");
    const cost = screen.getByTestId("sa-tile-cost");
    expect(cost).toHaveTextContent("500.000đ");
    expect(screen.getByTestId("sa-cost-ads")).toHaveTextContent("Quảng cáo");
    expect(screen.getByTestId("sa-cost-ads")).toHaveTextContent("Báo cáo DVHT");
    expect(screen.getByTestId("sa-cost-affiliate")).toHaveTextContent("96.000đ");
    expect(screen.getByTestId("sa-cost-offers")).toHaveTextContent("154.000đ");
    expect(screen.getByTestId("sa-tile-roi")).toHaveTextContent("5,4");
    expect(screen.getByTestId("sa-tile-roi")).not.toHaveTextContent("%5,4");
    expect(screen.getByTestId("sa-shift-roi")).toHaveTextContent("▲ 23 %");
  });

  it("GMV composition: Organic / Quảng cáo / Tiếp thị liên kết with % and value", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const comp = await screen.findByTestId("sa-composition");
    expect(within(comp).getByTestId("sa-comp-organic")).toHaveTextContent("28%");
    expect(within(comp).getByTestId("sa-comp-ads")).toHaveTextContent("63%");
    expect(within(comp).getByTestId("sa-comp-affiliate")).toHaveTextContent("1,20 tr đ");
  });

  it("every tile, composition item and cell links to Phân tích with metric / channel / period", async () => {
    renderWith(<TongQuanView params={params("ky=7d")} />, fakeApi());
    const q = (el: HTMLElement) => new URLSearchParams((el.getAttribute("href") ?? "").split("?")[1]);
    const tile = await screen.findByTestId("sa-tile-gmv");
    expect(tile.getAttribute("href")).toContain("/phan-tich");
    expect(q(tile).get("metric")).toBe("gmv");
    expect(q(tile).get("ky")).toBe("7d");
    expect(q(screen.getByTestId("sa-tile-roi")).get("metric")).toBe("margin");
    expect(q(screen.getByTestId("sa-comp-affiliate")).get("channel")).toBe("lien_ket");
    const cell = q(screen.getByTestId("sa-cell-organic_video-ctr"));
    expect([cell.get("metric"), cell.get("channel")]).toEqual(["ctr", "video"]);
    expect(q(screen.getByTestId("sa-cell-ads_shop-orders")).get("channel")).toBe("ads_shop");
    const row = within(screen.getByTestId("sa-channel-affiliate")).getAllByRole("link")[0] as HTMLElement;
    expect(q(row).get("channel")).toBe("lien_ket");
  });

  it("the picker has 7 / 30 / 90 ngày and Tùy chọn, no Tháng này; Tùy chọn opens the date fields", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const bar = await screen.findByTestId("sa-period");
    for (const label of ["7 ngày", "30 ngày", "90 ngày", "Tùy chọn"]) expect(within(bar).getByText(label)).toBeInTheDocument();
    expect(bar).not.toHaveTextContent(/Tháng này|So sánh kỳ trước/);
    expect(screen.getByTestId("sa-range")).toHaveTextContent("11/10–09/11");
    expect(screen.queryByTestId("sa-period-form")).toBeNull();
    await userEvent.click(screen.getByTestId("sa-period-custom"));
    expect(screen.getByTestId("sa-period-form")).toBeInTheDocument();
    expect(screen.getByLabelText("Từ ngày")).toBeInTheDocument();
  });

  it("Cả kế hoạch: offered after Tùy chọn, enabled with the span, links ky=ke-hoach", async () => {
    const base = channelSplit();
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: { ...base, plan_range: { from: "2026-10-15", to: "2026-10-24" } } }));
    const plan = await screen.findByTestId("sa-period-plan");
    expect(plan).toHaveTextContent("Cả kế hoạch");
    expect(plan.getAttribute("href")).toContain("ky=ke-hoach");
    const labels = Array.from(screen.getByTestId("sa-period").querySelectorAll(".sa-seg__item")).map((e) => e.textContent);
    expect(labels).toEqual(["7 ngày", "30 ngày", "90 ngày", "Tùy chọn", "Cả kế hoạch"]);
  });

  it("Cả kế hoạch is disabled without a running card", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: { ...channelSplit(), plan_range: null } }));
    const plan = await screen.findByTestId("sa-period-plan");
    expect(plan).toHaveAttribute("aria-disabled", "true");
    expect(plan.getAttribute("href")).toBeNull();
  });

  it("with ky=ke-hoach the resolved dates show as the range and links to other screens carry them as dates", async () => {
    const base = channelSplit();
    const split = { ...base, from: "2026-10-15", to: "2026-11-09", plan_range: { from: "2026-10-15", to: "2026-11-20" } };
    renderWith(<TongQuanView params={params("ky=ke-hoach")} />, fakeApi({ split }));
    expect(await screen.findByTestId("sa-range")).toHaveTextContent("15/10–09/11");
    expect(screen.getByTestId("sa-period-plan").getAttribute("aria-current")).toBe("true");
    const q = new URLSearchParams((screen.getByTestId("sa-tile-gmv").getAttribute("href") ?? "").split("?")[1]);
    expect([q.get("ky"), q.get("tu"), q.get("den")]).toEqual(["tuy-chon", "2026-10-15", "2026-11-09"]);
  });

  it("Trung bình / ngày (cach=tb) divides the summed figures, keeps the rates and ROI, and is carried to Phân tích", async () => {
    renderWith(<TongQuanView params={params("cach=tb")} />, fakeApi());
    await screen.findByTestId("sa-channels");
    expect(screen.getByTestId("sa-tile-gmv")).toHaveTextContent("GMV / ngày");
    expect(screen.getByTestId("sa-tile-gmv")).toHaveTextContent("429.667đ"); // 12,89 tr / 30
    expect(screen.getByTestId("sa-tile-roi")).toHaveTextContent("5,4");
    expect(screen.getByTestId("sa-cell-organic-ctr")).toHaveTextContent("5,8%"); // rates unchanged
    expect(within(screen.getByTestId("sa-channels")).getByText(/^GMV \/ ngày$/)).toBeInTheDocument();
    const q = (el: HTMLElement) => new URLSearchParams((el.getAttribute("href") ?? "").split("?")[1]);
    expect(q(screen.getByTestId("sa-tile-gmv")).get("cach")).toBe("tb");
    expect(q(screen.getByRole("link", { name: "Tổng" })).get("cach")).toBeNull();
    expect(screen.getByRole("link", { name: "7 ngày" }).getAttribute("href")).toContain("cach=tb");
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
    expect(keys()).toEqual(["organic", "organic_card", "organic_shop", "organic_video", "organic_live", "ads", "affiliate"]);
    expect(screen.getByTestId("sa-base-ads")).toHaveTextContent("Báo cáo DVHT");
    const href = (screen.getByTestId("sa-cell-organic-gmv").getAttribute("href") ?? "").split("?")[1];
    expect(new URLSearchParams(href).get("product")).toBe("1001");
    expect(screen.getByTestId("sa-product-open").getAttribute("href")).toContain("1001");
    // the weakest metric of the chosen product is marked in the header
    expect(screen.getByText("CTR").getAttribute("data-weak")).toBe("true");
    await userEvent.selectOptions(pick, "1002");
    await waitFor(() => expect(api.calls.some((c) => c.includes('"productId":"1002"'))).toBe(true));
  });

  it("Kế hoạch card is titled by the period: actual vs goal, green when ahead, today marker only when today is inside", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const card = await screen.findByTestId("sa-plan");
    expect(card).toHaveTextContent("Kế hoạch · 01/11 – 30/11");
    expect(card).toHaveTextContent("13/30 ngày");
    expect(screen.getByTestId("sa-plan-gmv")).toHaveTextContent("5,00 tr đ / 10,00 tr đ");
    expect(screen.getByTestId("sa-plan-gmv-fill").getAttribute("data-ahead")).toBe("true");
    expect(screen.getByTestId("sa-plan-profit-fill").getAttribute("data-ahead")).toBe("false");
    expect(screen.getByTestId("sa-plan-gmv-today").getAttribute("style")).toContain("43.33");
    await userEvent.click(screen.getByTestId("sa-plan-toggle"));
    expect(screen.queryByTestId("sa-plan")).toBeNull();
    expect(screen.getByTestId("sa-plan-toggle")).toHaveAttribute("aria-checked", "false");
  });

  it("a past period has no today marker", async () => {
    const base = channelSplit();
    renderWith(<TongQuanView params={params()} />, fakeApi({ split: { ...base, plan: { ...base.plan!, today_marker: null, day: 30 } } }));
    await screen.findByTestId("sa-plan-gmv-fill");
    expect(screen.queryByTestId("sa-plan-gmv-today")).toBeNull();
    expect(screen.getByTestId("sa-plan")).toHaveTextContent("30/30 ngày");
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
    expect(findingOf(channelSplit())).toBe("GMV ▲ 17 % · CTR Thẻ sản phẩm ▼ 9,4 %");
    expect(findingOf({ ...channelSplit(), kpis_prev: null })).toBe("CTR Thẻ sản phẩm ▼ 9,4 %");
    expect(aheadOfPace({ now: 5, goal: 10 }, 13, 30)).toBe(true);
    expect(aheadOfPace({ now: 3, goal: 10 }, 13, 30)).toBe(false);
    expect(aheadOfPace({ now: 3, goal: null }, 13, 30)).toBe(false);
    expect(channelProducts().products[0]?.weakest_metric).toBe("ctr");
  });
});
