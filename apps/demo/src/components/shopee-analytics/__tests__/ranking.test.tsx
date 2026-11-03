import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeApi, ranking } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { RankingPageView } from "../ranking-view";
import { params, renderWith, textOf } from "./harness";

const q = (href: string | null) => new URLSearchParams((href ?? "").split("?")[1] ?? "");

describe("Xếp hạng", () => {
  it("asks the API for the kpi's source, sub and measure (artboard keys → API keys)", async () => {
    const api = fakeApi();
    renderWith(<RankingPageView params={params("kpi=ctor&src=the_san_pham&sub=de_xuat&from=tong-quan")} />, api);
    await screen.findByTestId("sa-rk-table");
    expect(api.calls[0]).toBe('ranking:{"period":"30d","kind":"products","source":"the_san_pham_khac","sub":"recommend","xepTheo":"gmv_per_day"}');
  });

  it("names the cell, the window and the source chip; the context cell is the number the rows add up to", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&src=all")} />, fakeApi());
    expect(await screen.findByRole("heading", { level: 1, name: "Xếp hạng GMV · Tất cả" })).toBeInTheDocument();
    expect(screen.getByTestId("sa-rk-window")).toHaveTextContent("30 ngày · so với 30 ngày trước");
    const ctx = screen.getByTestId("sa-ctx");
    expect(ctx).toHaveTextContent("450.000đ/ngày");
    expect(ctx).toHaveTextContent("−90.000đ/ngày");
    expect(ctx).toHaveTextContent("Các dòng bên dưới cộng lại đúng bằng số này.");
  });

  it("source chips: the five flows, ads (trong đó) and the four levers; Thẻ sản phẩm has a sub-row of six children", async () => {
    renderWith(<RankingPageView params={params("kpi=ctr&src=the_san_pham&sub=search")} />, fakeApi());
    await screen.findByTestId("sa-rk-table");
    for (const name of ["Tất cả", "Thẻ sản phẩm", "Trang shop", "Live", "Video", "Tiếp thị liên kết", "Quảng cáo (trong đó)", "Không ưu đãi", "Voucher", "Khuyến mãi", "Combo"]) {
      expect(screen.getAllByRole("link", { name }).length).toBeGreaterThan(0);
    }
    const subs = screen.getByTestId("sa-subchips");
    for (const name of ["Cả Thẻ sản phẩm", "Tìm kiếm", "Đề xuất", "Giỏ hàng", "Đơn mua của tôi", "Khuyến mãi (gồm Flash Sale)", "Khác"]) {
      expect(within(subs).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(subs).getByRole("link", { name: "Tìm kiếm" })).toHaveAttribute("aria-current", "true");
    const de = within(subs).getByRole("link", { name: "Đề xuất" });
    expect(Object.fromEntries(q(de.getAttribute("href")))).toEqual({ kpi: "ctr", src: "the_san_pham", sub: "de_xuat" });
  });

  it("the sub-row is only there for Thẻ sản phẩm", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&src=live")} />, fakeApi());
    await screen.findByTestId("sa-rk-table");
    expect(screen.queryByTestId("sa-subchips")).toBeNull();
  });

  it("'Xếp theo' switches the measure and keeps the cell", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&src=voucher&loai=products")} />, fakeApi());
    await screen.findByTestId("sa-rk-table");
    const profit = screen.getByRole("link", { name: "₫ lợi nhuận/ngày" });
    expect(Object.fromEntries(q(profit.getAttribute("href")))).toMatchObject({ kpi: "gmv", src: "voucher", xep: "profit", loai: "products" });
    for (const name of ["₫ GMV/ngày", "₫ lợi nhuận/ngày", "Biên cuối", "Số đơn", "AOV", "% giảm giá"]) {
      expect(screen.getAllByRole("link", { name }).length).toBeGreaterThan(0);
    }
  });

  it("the rows, the closing rows and the total add up to the cell (Kéo xuống)", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&src=all&huong=xuong")} />, fakeApi());
    const table = await screen.findByTestId("sa-rk-table");
    expect(within(table).getByTestId("sa-rk-row-XM-003")).toHaveTextContent("−100.000đ/ngày");
    expect(within(table).getByTestId("sa-rk-row-GN-005")).toHaveTextContent("−30.000đ/ngày");
    expect(within(table).queryByTestId("sa-rk-row-BEP-S5")).toBeNull();
    const closing = within(table).getByTestId("sa-rk-closing");
    expect(closing).toHaveTextContent("2 sản phẩm ít đơn");
    expect(closing).toHaveTextContent("Các sản phẩm khác");
    expect(closing).toHaveTextContent("Các sản phẩm kéo lên");
    expect(closing).toHaveTextContent("Thay đổi cơ cấu sản phẩm");
    // rows −130.000 + closing +40.000 = −90.000 = the cell
    expect(within(table).getByTestId("sa-rk-total")).toHaveTextContent("−90.000đ/ngày");
    expect(within(table).getByTestId("sa-rk-check")).toHaveTextContent("Σ các dòng + các dòng còn lại = −90.000đ/ngày ✓ cộng đúng");
  });

  it("Kéo lên shows the other direction and still adds up", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&src=all&huong=len")} />, fakeApi());
    const table = await screen.findByTestId("sa-rk-table");
    expect(within(table).getByTestId("sa-rk-row-BEP-S5")).toHaveTextContent("+50.000đ/ngày");
    expect(within(table).queryByTestId("sa-rk-row-XM-003")).toBeNull();
    expect(within(table).getByTestId("sa-rk-closing")).toHaveTextContent("Các sản phẩm kéo xuống");
    expect(within(table).getByTestId("sa-rk-total")).toHaveTextContent("−90.000đ/ngày");
  });

  it("defaults the direction to the cell's sign (a falling cell opens on Kéo xuống)", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv")} />, fakeApi());
    expect(await screen.findByTestId("sa-rk-row-XM-003")).toBeInTheDocument();
  });

  it("opens on the direction of the focused row", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&focus=BEP-S5")} />, fakeApi());
    expect(await screen.findByTestId("sa-rk-row-BEP-S5")).toBeInTheDocument();
  });

  it("each row shows trước → nay, orders, confidence and → đề xuất / chưa có đề xuất", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&src=all&huong=xuong")} />, fakeApi());
    const xm = await screen.findByTestId("sa-rk-row-XM-003");
    expect(xm).toHaveTextContent("200.000đ → 100.000đ");
    expect(xm).toHaveTextContent("50 → 40 đơn");
    expect(xm).toHaveTextContent("Rõ");
    const rec = within(xm).getByRole("link", { name: /→ 3\.000\.000đ\/tháng/ });
    expect(Object.fromEntries(q(rec.getAttribute("href")))).toMatchObject({ the: "c_xm_disc", from: "xep-hang", row: "XM-003" });
    const gn = screen.getByTestId("sa-rk-row-GN-005");
    expect(gn).toHaveTextContent("Tham khảo");
    expect(gn).toHaveTextContent("Chưa có đề xuất");
  });

  it("a row opens into 'Mở sản phẩm ›' with kpi, src, sub, row and from=ranking", async () => {
    renderWith(<RankingPageView params={params("kpi=ctor&src=the_san_pham&sub=de_xuat&huong=xuong")} />, fakeApi());
    const user = userEvent.setup();
    const row = await screen.findByTestId("sa-rk-row-XM-003");
    await user.click(within(row).getByRole("button", { name: /Xơ mướp rửa chén/ }));
    const open = within(row).getByRole("link", { name: /Mở sản phẩm ›/ });
    expect(open.getAttribute("href")?.split("?")[0]).toBe("/san-pham/XM-003");
    expect(Object.fromEntries(q(open.getAttribute("href")))).toEqual({ tab: "ng", kpi: "ctor", src: "the_san_pham", sub: "de_xuat", row: "XM-003", from: "ranking" });
  });

  it("a non-additive measure says its rows do not add up and sorts by value", async () => {
    const r = ranking({
      xep_theo: { key: "bien", label: "Biên cuối", additive: false },
      cell: { now: 20.9, before: 22.1, delta: -1.2 },
      views: {},
      adds_up: null,
      adds_up_note: "Đại lượng tỷ lệ (biên, AOV, % giảm giá, thu thêm / chi thêm) không cộng được; chỉ xếp theo thay đổi.",
    });
    renderWith(<RankingPageView params={params("kpi=bien&xep=bien")} />, fakeApi({ ranking: r }));
    expect(await screen.findByTestId("sa-rk-nonadd")).toHaveTextContent("không cộng được");
    expect(screen.queryByTestId("sa-rk-closing")).toBeNull();
    expect(screen.getByRole("link", { name: "Thấp → cao" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Cao → thấp" })).toBeInTheDocument();
    const rows = screen.getAllByTestId(/^sa-rk-row-/).map((e) => e.getAttribute("data-testid"));
    expect(rows[0]).toBe("sa-rk-row-GN-005");
  });

  it("an unsupported combination explains itself instead of drawing an empty table", async () => {
    const r = ranking({ supported: false, reason: "not_split_by_flow", message: "Lợi nhuận, biên không tách được theo luồng lưu lượng.", cell: undefined, down: undefined, up: undefined, views: undefined, closing: undefined });
    renderWith(<RankingPageView params={params("kpi=bien&src=live")} />, fakeApi({ ranking: r }));
    expect(await screen.findByTestId("sa-rk-unsupported")).toHaveTextContent("không tách được theo luồng");
    expect(screen.queryByTestId("sa-rk-table")).toBeNull();
  });

  it("campaign rows (ads) carry the placed-order label", async () => {
    const r = ranking({ kind: "campaigns", source: "ads", ads_basis: { key: "placed", label: "đơn đã đặt" }, ads_note: "Quảng cáo tính theo đơn đã đặt." });
    renderWith(<RankingPageView params={params("kpi=gmv&src=ads")} />, fakeApi({ ranking: r }));
    expect(await screen.findByTestId("sa-ads-note")).toHaveTextContent("đơn đã đặt");
    expect(screen.getByRole("heading", { level: 1, name: "Xếp hạng GMV · Quảng cáo" })).toBeInTheDocument();
  });

  it("an empty direction says so", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv&huong=len")} />, fakeApi({ ranking: ranking({ up: [] }) }));
    expect(await screen.findByTestId("sa-rk-empty")).toBeInTheDocument();
  });

  it("never draws a buyer field", async () => {
    const { container } = renderWith(<RankingPageView params={params()} />, fakeApi());
    await screen.findByTestId("sa-rk-table");
    expect(textOf(container).toLowerCase()).not.toContain("buyer");
  });
});

describe("Xếp hạng: coming back from a card or a product", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("highlights the focus row for three seconds, with the banner and 'Về thẻ ›'", async () => {
    renderWith(<RankingPageView params={params("kpi=ctor&src=the_san_pham&sub=de_xuat&focus=XM-003&from=card&card=c_xm_disc")} />, fakeApi());
    const row = await screen.findByTestId("sa-rk-row-XM-003");
    expect(row.className).toContain("sa-rcard--focus");
    expect(row).toHaveTextContent("Vừa xem ở thẻ");
    const banner = screen.getByTestId("sa-card-banner");
    expect(banner).toHaveTextContent("Vừa quay về từ thẻ");
    expect(banner).toHaveTextContent("c_xm_disc");
    expect(within(banner).getByRole("link", { name: "Về thẻ ›" }).getAttribute("href")).toContain("the=c_xm_disc");
    expect(screen.getByRole("link", { name: "‹ Thẻ đề xuất" })).toBeInTheDocument();
    // Let the effect that arms the timer run, then let the three seconds pass.
    await act(async () => {
      vi.advanceTimersByTime(50);
    });
    await act(async () => {
      vi.advanceTimersByTime(3100);
    });
    await waitFor(() => expect(screen.getByTestId("sa-rk-row-XM-003").className).not.toContain("sa-rcard--focus"));
    expect(screen.getByTestId("sa-rk-row-XM-003")).not.toHaveTextContent("Vừa xem ở thẻ");
  });

  it("the back link goes where the person came from", async () => {
    const { unmount } = renderWith(<RankingPageView params={params("kpi=gmv&from=phan-tich")} />, fakeApi());
    expect(await screen.findByRole("link", { name: "‹ Phân tích" })).toHaveAttribute("href", "/phan-tich");
    unmount();
    renderWith(<RankingPageView params={params("kpi=gmv&focus=BEP-S5&from=san-pham")} />, fakeApi());
    expect(await screen.findByRole("link", { name: "‹ Sản phẩm" })).toHaveAttribute("href", "/san-pham/BEP-S5?tab=ng");
  });

  it("defaults the back link to Tổng quan", async () => {
    renderWith(<RankingPageView params={params("kpi=gmv")} />, fakeApi());
    expect(await screen.findByRole("link", { name: "‹ Tổng quan" })).toHaveAttribute("href", "/tong-quan");
  });
});
