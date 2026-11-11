import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { fakeApi, matrix, matrixProduct, overview } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { TongQuanView } from "../tong-quan";
import { params, renderWith, textOf } from "./harness";

const q = (href: string | null) => new URLSearchParams((href ?? "").split("?")[1] ?? "");

describe("Tổng quan", () => {
  it("opens with the KPI tiles (P100 B.6), each linking to Phân tích set to its KPI", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-tile-gmv")).toHaveTextContent("50.000.000đ");
    expect(screen.getByTestId("sa-tile-views")).toHaveTextContent("68.000");
    expect(screen.getByTestId("sa-tile-ctr")).toHaveTextContent("4,41%");
    expect(screen.getByTestId("sa-tile-ctor")).toHaveTextContent("8,33%");
    expect(screen.getByTestId("sa-tile-aov")).toHaveTextContent("200.000đ");
    expect(screen.getByTestId("sa-tile-orders")).toHaveTextContent("250");
    // P100 B.5: Tổng lợi nhuận is the one shop profit with its coverage line
    expect(screen.getByTestId("sa-tile-profit")).toHaveTextContent("8.850.000đ");
    expect(screen.getByTestId("sa-tile-profit")).toHaveTextContent("Biên 20,9%");
    expect(screen.getByTestId("sa-tile-profit")).toHaveTextContent("trên 240 đơn có chi phí, 96,0 % GMV");
    expect(q(screen.getByTestId("sa-tile-profit").getAttribute("href")).get("kpi")).toBe("profit");
    expect(screen.queryByTestId("sa-tile-bien")).toBeNull();
    const href = screen.getByTestId("sa-tile-ctr").getAttribute("href");
    expect(href?.split("?")[0]).toBe("/phan-tich");
    expect(Object.fromEntries(q(href))).toEqual({ kpi: "ctr", src: "all", from: "tong-quan" });
  });

  it("shows the ₫/ngày each link pulled and flags the weakest one", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const ctr = await screen.findByTestId("sa-tile-ctr");
    expect(ctr).toHaveTextContent("✦ Juli gợi ý");
    expect(ctr.textContent).toMatch(/−[\d.]+đ\/ngày/);
    expect(screen.getByTestId("sa-tile-gmv")).toHaveTextContent("Tổng 4 ô: +");
  });

  it("P100 B.6: no '5 con số chính', no second AOV, no 'Mức ưu đãi trên mỗi dòng đơn'", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-tile-gmv");
    expect(screen.queryByTestId("sa-five")).toBeNull();
    expect(screen.queryByTestId("sa-aov-note")).toBeNull();
    expect(screen.queryByTestId("sa-levers")).toBeNull();
    expect(screen.getByTestId("sa-tong-quan")).not.toHaveTextContent("AOV theo Seller Centre");
    expect(screen.getByTestId("sa-tong-quan")).not.toHaveTextContent("ước tính theo tỉ lệ");
  });

  it("with partial cost coverage shows margin on X %, no profit in đồng, and the real / assumed / unknown split", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const profit = await screen.findByTestId("sa-profit");
    expect(within(profit).getByTestId("sa-margin")).toHaveTextContent("20,9%");
    expect(profit).toHaveTextContent("trên 99,4% doanh thu có giá vốn");
    // P100 B.5: the one shop profit shows in đồng with its coverage line, even when partial
    expect(profit).toHaveTextContent("= Lợi nhuận shop");
    expect(profit).toHaveTextContent("8.850.000đ");
    expect(profit).toHaveTextContent("trên 240 đơn có chi phí, 96,0 % GMV");
    expect(within(profit).getByTestId("sa-coverage")).toHaveTextContent("Giá vốn thật: 88,0%");
    expect(within(profit).getByTestId("sa-coverage")).toHaveTextContent("giá vốn giả định (1/3 giá): 11,4%");
    expect(within(profit).getByTestId("sa-coverage")).toHaveTextContent("chưa có: 0,6%");
    expect(within(profit).getByTestId("sa-assumed-label")).toHaveTextContent("11,4% doanh thu dùng giá vốn giả định (1/3 giá)");
    expect(within(profit).getByTestId("sa-ad-check")).toHaveTextContent("QC các sản phẩm 3.400.000đ + QC không gắn sản phẩm 600.000đ = tổng chi QC 4.000.000đ ✓");
    expect(profit).not.toHaveTextContent("8.900.000đ");
  });

  it("at 100 % coverage shows the shop profit in đồng", async () => {
    const ov = overview();
    renderWith(
      <TongQuanView params={params()} />,
      fakeApi({
        overview: {
          ...ov,
          profit: { ...ov.profit, profit_is_partial: false, profit_vnd: 9_250_000, cost_coverage: { ...ov.profit.cost_coverage, real_pct: 100, assumed_pct: 0, unknown_pct: 0 }, assumed_cost_share_pct: 0, missing: {} },
        },
      }),
    );
    const profit = await screen.findByTestId("sa-profit");
    expect(profit).toHaveTextContent("= Lợi nhuận shop");
    expect(profit).toHaveTextContent("9.250.000đ");
    expect(profit).toHaveTextContent("cùng số với Sản phẩm và Kế hoạch");
    expect(profit).toHaveTextContent("trên 100% doanh thu khách trả");
    expect(screen.queryByTestId("sa-assumed-label")).toBeNull();
  });

  it("draws the five flows and Chênh lệch nguồn so that they add up to the shop GMV", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const tree = await screen.findByTestId("sa-tree");
    for (const key of ["the_san_pham_khac", "trang_shop", "live", "video", "lien_ket"]) {
      expect(within(tree).getByTestId(`sa-flow-${key}`)).toBeInTheDocument();
    }
    expect(within(tree).getByTestId("sa-residual")).toHaveTextContent("Chênh lệch nguồn");
    expect(within(tree).getByTestId("sa-residual")).toHaveTextContent("+500.000đ");
    expect(within(tree).getByTestId("sa-sum-check")).toHaveTextContent("Σ năm luồng 50.000.000đ + chênh lệch 500.000đ = GMV shop 50.000.000đ");
    expect(within(tree).getByTestId("sa-tsp-note")).toHaveTextContent("Thẻ sản phẩm (ngoài Trang shop) 28.000.000đ + Trang shop 6.000.000đ");
  });

  it("opens the six Thẻ sản phẩm children as a drill-down with their own links", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const tree = await screen.findByTestId("sa-tree");
    expect(within(tree).queryByTestId("sa-kid-search")).toBeNull();
    await user.click(within(tree).getByRole("button", { name: "Mở các nguồn con" }));
    for (const key of ["search", "recommend", "cart", "my_orders", "promo", "other"]) {
      expect(within(tree).getByTestId(`sa-kid-${key}`)).toBeInTheDocument();
    }
    const recommend = within(within(tree).getByTestId("sa-kid-recommend")).getAllByRole("link")[0]!;
    expect(Object.fromEntries(q(recommend.getAttribute("href")))).toMatchObject({ src: "the_san_pham", sub: "de_xuat", from: "tong-quan" });
  });

  it("shows ads as a dashed 'trong đó' row with the placed-order label, and can hide it", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const row = await screen.findByTestId("sa-ads-row");
    expect(row).toHaveTextContent("trong đó Quảng cáo");
    expect(row).toHaveTextContent("đơn đã đặt");
    expect(row).toHaveTextContent("16.000.000đ");
    await user.click(screen.getByRole("button", { name: "Ẩn Quảng cáo (trong đó)" }));
    expect(screen.queryByTestId("sa-ads-row")).toBeNull();
  });

  it("explains an empty flows table instead of drawing zeros", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi({ overview: overview({ flows: { available: false } }) }));
    expect(await screen.findByTestId("sa-flows-empty")).toHaveTextContent("Chưa có lưu lượng theo nguồn");
  });

  it("stale data: names each source with the days it covers and warns", async () => {
    const ov = overview();
    renderWith(
      <TongQuanView params={params()} />,
      fakeApi({ overview: { ...ov, data: { ...ov.data, ads_daily: { days_covered: 24 }, order_lines: { ...ov.data.order_lines, covers_window: false, days_with_orders: 27 } }, warnings: [{ code: "order_lines_partial", message: "File đơn hàng chưa phủ hết kỳ." }] } }),
    );
    const stale = await screen.findByTestId("sa-stale");
    expect(stale).toHaveTextContent("Quảng cáo: 24/30 ngày");
    expect(stale).toHaveTextContent("Đơn hàng: 27/30 ngày");
    expect(screen.getByTestId("sa-fresh")).toHaveTextContent("Dữ liệu chưa đủ kỳ");
    expect(screen.getByTestId("sa-warning-order_lines_partial")).toHaveTextContent("File đơn hàng chưa phủ hết kỳ.");
    expect(screen.getByTestId("sa-tile-gmv")).toHaveTextContent("Tính đến 02/11");
  });

  it("period picker: 7 / 30 / 90 ngày, month, custom window and 'so sánh kỳ trước' are links that carry the window", async () => {
    const api = fakeApi();
    renderWith(<TongQuanView params={params("ky=7d")} />, api);
    const bar = await screen.findByTestId("sa-period");
    expect(api.calls[0]).toContain('"period":"7d"');
    expect(q(within(bar).getByRole("link", { name: "90 ngày" }).getAttribute("href")).get("ky")).toBe("90d");
    expect(within(bar).getByRole("link", { name: "30 ngày" }).getAttribute("href")).toBe("/tong-quan");
    const toggle = within(bar).getByRole("link", { name: "So sánh kỳ trước: bật" });
    expect(q(toggle.getAttribute("href")).get("cmp")).toBe("0");
    expect(within(bar).getByTestId("sa-range")).toHaveTextContent("04/10–02/11 so với 04/09–03/10");
    const user = userEvent.setup();
    await user.click(within(bar).getByText("Chọn tháng hoặc khoảng ngày ▾"));
    expect(q(within(bar).getByRole("link", { name: "Xem tháng" }).getAttribute("href")).get("thang")).toBe("2026-11");
    expect(within(bar).getByRole("link", { name: "Xem khoảng này" })).toBeInTheDocument();
  });

  it("with comparison off, no previous chips and no previous window text", async () => {
    renderWith(<TongQuanView params={params("cmp=0")} />, fakeApi());
    const bar = await screen.findByTestId("sa-period");
    expect(within(bar).getByTestId("sa-range")).not.toHaveTextContent("so với");
    expect(screen.getByTestId("sa-tile-gmv")).not.toHaveTextContent("▲");
  });

  it("calls the API with a custom window", async () => {
    const api = fakeApi();
    renderWith(<TongQuanView params={params("ky=tuy-chon&tu=2026-10-01&den=2026-10-20")} />, api);
    await screen.findByTestId("sa-tile-gmv");
    expect(api.calls[0]).toBe('overview:{"period":"custom","from":"2026-10-01","to":"2026-10-20"}');
  });

  it("each state of a refusal is its own screen", async () => {
    const { unmount } = renderWith(<TongQuanView params={params()} />, fakeApi({}, new ShopeeApiError(409, "not_a_shopee_shop", "x")));
    expect(await screen.findByTestId("sa-refusal-not-shopee")).toHaveTextContent("không phải shop Shopee");
    unmount();
    renderWith(<TongQuanView params={params()} />, fakeApi({}, new ShopeeApiError(409, "no_shopee_data", "x")));
    expect(await screen.findByTestId("sa-refusal-no-data")).toHaveTextContent("chưa có dữ liệu Shopee");
  });

  it("never draws a buyer field", async () => {
    const { container } = renderWith(<TongQuanView params={params()} />, fakeApi());
    await screen.findByTestId("sa-matrix");
    await waitFor(() => expect(screen.getByTestId("sa-mrow-BEP-S5")).toBeInTheDocument());
    expect(textOf(container).toLowerCase()).not.toContain("buyer");
    expect(textOf(container)).not.toContain("buyer_paid");
  });
});

describe("Tổng quan: product × source matrix", () => {
  it("lists the products with nine numbers and the 'chưa có đề xuất' / '→ đề xuất' chips", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const row = await screen.findByTestId("sa-mrow-BEP-S5");
    expect(row).toHaveTextContent("Bộ vệ sinh bếp 5 món");
    expect(row).toHaveTextContent("12.000.000đ");
    const rec = within(row).getByRole("link", { name: /→ \+1\.500\.000đ\/th/ });
    expect(Object.fromEntries(q(rec.getAttribute("href")))).toEqual({ the: "c_bep_voucher", from: "tong-quan" });
    expect(rec.getAttribute("href")?.split("?")[0]).toBe("/decisions");
    expect(within(screen.getByTestId("sa-mrow-GL-001")).getByText("Chưa có đề xuất")).toBeInTheDocument();
  });

  it("a cell opens Phân tích set to its KPI", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const row = await screen.findByTestId("sa-mrow-BEP-S5");
    const bien = within(row).getByText("③ Biên cuối", { selector: "span" }).closest("a");
    expect(Object.fromEntries(q(bien?.getAttribute("href") ?? null))).toEqual({ kpi: "bien", src: "all", from: "tong-quan" });
  });

  it("opening a product shows its five flows, the residual row, the ads overlay and 'Mở sản phẩm ›'", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const row = await screen.findByTestId("sa-mrow-BEP-S5");
    await user.click(within(row).getByRole("button", { name: /Bộ vệ sinh bếp 5 món/ }));
    const src = screen.getByTestId("sa-sources-BEP-S5");
    for (const key of ["the_san_pham_khac", "trang_shop", "live", "video", "lien_ket"]) {
      expect(within(src).getByTestId(`sa-pflow-BEP-S5-${key}`)).toBeInTheDocument();
    }
    expect(within(src).getByTestId("sa-pads-BEP-S5")).toHaveTextContent("đơn đã đặt");
    expect(within(src).queryByTestId("sa-nofive-BEP-S5")).toBeNull();
    const open = within(src).getByRole("link", { name: "Mở sản phẩm ›" });
    expect(open.getAttribute("href")).toBe("/san-pham/BEP-S5?tab=ng&from=tong-quan");
  });

  it("a product without the Trang shop split says it has four flows (trang_shop_available: false)", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const row = await screen.findByTestId("sa-mrow-GL-001");
    await user.click(within(row).getByRole("button", { name: /Găng tay/ }));
    expect(screen.getByTestId("sa-nofive-GL-001")).toHaveTextContent("trang_shop_available: false");
  });

  it("a product with no flow data says so instead of drawing zeros", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const row = await screen.findByTestId("sa-mrow-XM-003");
    await user.click(within(row).getByRole("button", { name: /Xơ mướp/ }));
    expect(screen.getByTestId("sa-noflows-XM-003")).toBeInTheDocument();
  });

  it("switches to price levers: four levers, views / CTR / CTOR not split", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    const row = await screen.findByTestId("sa-mrow-BEP-S5");
    await user.click(screen.getByRole("button", { name: "Theo ưu đãi" }));
    await user.click(within(row).getByRole("button", { name: /Bộ vệ sinh bếp 5 món/ }));
    for (const key of ["khong_uu_dai", "voucher", "khuyen_mai", "combo"]) {
      expect(screen.getByTestId(`sa-lever-BEP-S5-${key}`)).toBeInTheDocument();
    }
    expect(screen.getByTestId("sa-lever-BEP-S5-voucher")).toHaveTextContent("Lượt xem");
    const voucher = within(screen.getByTestId("sa-lever-BEP-S5-voucher")).getAllByRole("link")[1]!;
    expect(q(voucher.getAttribute("href")).get("src")).toBe("voucher");
  });

  it("sorts by any column and by margin ascending first", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    const user = userEvent.setup();
    await screen.findByTestId("sa-mrow-BEP-S5");
    const order = () => screen.getAllByTestId(/^sa-mrow-/).map((e) => e.getAttribute("data-testid"));
    expect(order()).toEqual(["sa-mrow-BEP-S5", "sa-mrow-GL-001", "sa-mrow-XM-003"]);
    await user.click(screen.getByRole("button", { name: "Sắp theo ③ Biên cuối" }));
    expect(order()[0]).toBe("sa-mrow-GL-001");
    expect(screen.getByTestId("sa-sort-note")).toHaveTextContent("Sắp theo Biên cuối thấp → cao");
    await user.click(screen.getByRole("button", { name: "Sắp theo ④ Đơn" }));
    expect(order()).toEqual(["sa-mrow-BEP-S5", "sa-mrow-GL-001", "sa-mrow-XM-003"]);
  });

  it("filters: biên dưới mục tiêu and có đề xuất; an empty filter says so", async () => {
    const m = matrix({ products: [matrixProduct("A", { card: null }), matrixProduct("B", { card: { id: "c_b" } })] });
    renderWith(<TongQuanView params={params()} />, fakeApi({ matrix: m }));
    const user = userEvent.setup();
    await screen.findByTestId("sa-mrow-A");
    await user.click(screen.getByRole("button", { name: /Có đề xuất · 1/ }));
    expect(screen.queryByTestId("sa-mrow-A")).toBeNull();
    expect(screen.getByTestId("sa-mrow-B")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Biên dưới mục tiêu · 0/ }));
    expect(screen.getByTestId("sa-matrix-empty")).toBeInTheDocument();
  });

  it("closes with the gap between the shop GMV and the sum of the products", async () => {
    renderWith(<TongQuanView params={params()} />, fakeApi());
    expect(await screen.findByTestId("sa-matrix-gap")).toHaveTextContent("+24.000.000đ");
    expect(screen.getByTestId("sa-matrix-total")).toHaveTextContent("50.000.000đ");
  });

  it("compares each cell with the previous window read from the same matrix API", async () => {
    const api = fakeApi();
    renderWith(<TongQuanView params={params()} />, api);
    await screen.findByTestId("sa-mrow-BEP-S5");
    await waitFor(() => expect(api.calls.some((c) => c.startsWith("matrix:") && c.includes('"period":"custom"'))).toBe(true));
    expect(api.calls.find((c) => c.includes('"period":"custom"'))).toContain('"from":"2026-09-04","to":"2026-10-03"');
  });
});

describe("Tổng quan: sản phẩm đã loại trừ (P92 B-1)", () => {
  it("shows 'trong đó Xđ từ sản phẩm đã loại trừ' under the figures only when the excluded GMV is above 0, linking to the list", async () => {
    const base = overview();
    const withExcluded = overview({ gmv: { ...base.gmv, excluded_gmv: 1_950_000 } });
    const { unmount } = renderWith(<TongQuanView params={params()} />, fakeApi({ overview: withExcluded }));
    const line = await screen.findByTestId("sa-excluded-gmv");
    expect(line).toHaveTextContent("trong đó 1.950.000đ từ sản phẩm đã loại trừ");
    expect(screen.getByTestId("sa-excluded-gmv-link")).toHaveAttribute("href", "/settings?tab=loai-tru-san-pham");
    unmount();
    for (const excluded of [0, null, undefined]) {
      const none = overview({ gmv: { ...base.gmv, excluded_gmv: excluded } });
      const r = renderWith(<TongQuanView params={params()} />, fakeApi({ overview: none }));
      await screen.findByTestId("sa-tile-gmv");
      expect(screen.queryByTestId("sa-excluded-gmv")).toBeNull();
      r.unmount();
    }
  });
});
