import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { fakeApi, matrix, matrixProduct, product } from "../../../lib/shopee-analytics/__tests__/fixtures";
import type { ProductPage } from "../../../lib/shopee-analytics/types";
import { ProductListView } from "../product-list";
import { ProductPageView } from "../product-page";
import { params, renderWith, textOf } from "./harness";

const q = (href: string | null) => new URLSearchParams((href ?? "").split("?")[1] ?? "");
const page = (qs = "tab=ng", p?: ProductPage, readOnly = false) =>
  renderWith(<ProductPageView id="BEP-S5" params={params(qs)} />, fakeApi({ product: p ?? product() }), { readOnly });

describe("Sản phẩm: the listing header", () => {
  it("shows image, title, Mã SP, SKU with the variation count, category and status", async () => {
    page();
    const hero = await screen.findByTestId("sa-hero");
    expect(within(hero).getByAltText("Bộ vệ sinh bếp 5 món set rửa chén")).toHaveAttribute("src", "https://img.example/bep-s5-1.jpg");
    expect(within(hero).getByTestId("sa-title")).toHaveTextContent("Bộ vệ sinh bếp 5 món set rửa chén");
    expect(hero).toHaveTextContent("35/120 ký tự");
    expect(within(hero).getByTestId("sa-pid")).toHaveTextContent("BEP-S5");
    expect(hero).toHaveTextContent("BEP-S5-CB");
    expect(hero).toHaveTextContent("+ 1 phiên bản");
    expect(hero).toHaveTextContent("Nhà Cửa & Đời Sống › Dụng Cụ Nhà Bếp › Bộ Dụng Cụ Vệ Sinh Bếp");
    expect(hero).toHaveTextContent("● Đang bán");
  });

  it("copies the Mã SP", async () => {
    const user = userEvent.setup();
    page();
    await user.click(await screen.findByRole("button", { name: "Sao chép" }));
    expect(await navigator.clipboard.readText()).toBe("BEP-S5");
    expect(await screen.findByRole("button", { name: "Đã sao chép ✓" })).toBeInTheDocument();
  });

  it("has no version stepper while there is a single snapshot", async () => {
    page();
    await screen.findByTestId("sa-hero");
    expect(screen.queryByTestId("sa-image-stepper")).toBeNull();
  });

  it("steps through image versions when snapshots exist", async () => {
    const p = product();
    page(
      "tab=ng",
      {
        ...p,
        header: {
          ...p.header,
          versions: [
            { captured_at: "2026-10-01T00:00:00Z", images: ["https://img.example/v1.jpg"] },
            { captured_at: "2026-10-20T00:00:00Z", images: ["https://img.example/v2.jpg"] },
            { captured_at: "2026-11-03T00:00:00Z", images: ["https://img.example/v3.jpg"] },
          ],
        },
      },
    );
    const user = userEvent.setup();
    const stepper = await screen.findByTestId("sa-image-stepper");
    expect(stepper).toHaveTextContent("Phiên bản 3/3");
    expect(screen.getByAltText("Bộ vệ sinh bếp 5 món set rửa chén")).toHaveAttribute("src", "https://img.example/v3.jpg");
    expect(within(stepper).getByRole("button", { name: "Phiên bản ảnh mới hơn" })).toBeDisabled();
    await user.click(within(stepper).getByRole("button", { name: "Phiên bản ảnh cũ hơn" }));
    expect(stepper).toHaveTextContent("Phiên bản 2/3");
    expect(screen.getByAltText("Bộ vệ sinh bếp 5 món set rửa chén")).toHaveAttribute("src", "https://img.example/v2.jpg");
  });

  it("does not crash on backend-shaped versions (cover_url ids, no images array) and shows the no-image hint", async () => {
    const p = product();
    const v = (captured_at: string, first = false) => ({
      captured_at,
      title: null,
      title_chars: null,
      list_price: 200000,
      current_price: 190000,
      cover_url: "vn-11134207-81ztc-synthetic01",
      image_count: 1,
      changes: [],
      first,
    });
    page("tab=hs", {
      ...p,
      header: { ...p.header, images: ["vn-11134207-81ztc-synthetic01"], versions: [v("2026-10-01T00:00:00Z", true), v("2026-10-20T00:00:00Z"), v("2026-11-03T00:00:00Z")] },
    } as ProductPage);
    const hero = await screen.findByTestId("sa-hero");
    expect(hero).toHaveTextContent("Chưa có ảnh sản phẩm");
    expect(hero.querySelector("img")).toBeNull();
    expect(screen.getByTestId("sa-image-stepper")).toHaveTextContent("Phiên bản 3/3");
  });

  it("opens on the newest version when the backend sends them newest first", async () => {
    const p = product();
    page("tab=hs", {
      ...p,
      header: {
        ...p.header,
        versions: [
          { captured_at: "2026-11-03T00:00:00Z", cover_url: "https://img.example/new.jpg" },
          { captured_at: "2026-10-01T00:00:00Z", cover_url: "https://img.example/old.jpg" },
        ],
      },
    } as ProductPage);
    expect(await screen.findByAltText("Bộ vệ sinh bếp 5 món set rửa chén")).toHaveAttribute("src", "https://img.example/new.jpg");
  });

  it("uses a URL cover_url from a version and tolerates a header without images", async () => {
    const p = product();
    page("tab=hs", {
      ...p,
      header: { ...p.header, images: undefined, versions: [{ captured_at: "2026-11-03T00:00:00Z", cover_url: "https://img.example/c.jpg" }] },
    } as ProductPage);
    expect(await screen.findByAltText("Bộ vệ sinh bếp 5 món set rửa chén")).toHaveAttribute("src", "https://img.example/c.jpg");
  });

  it("price block: list, selling, customer-paid, floors and max discount", async () => {
    page();
    const price = await screen.findByTestId("sa-price");
    expect(price).toHaveTextContent("200.000đ");
    expect(price).toHaveTextContent("Đang bán 190.000đ");
    expect(price).toHaveTextContent("khách trả 190.000đ sau voucher");
    expect(price).toHaveTextContent("Voucher shop 10.000đ");
    expect(within(price).getByTestId("sa-floor-abs")).toHaveTextContent("121.176đ");
    expect(within(price).getByTestId("sa-floor-op")).toHaveTextContent("181.979đ");
    expect(within(price).getByTestId("sa-maxdisc")).toHaveTextContent("9,0% · 18.000đ");
    expect(within(price).getByTestId("sa-price-fresh")).toHaveTextContent("Cập nhật 03/11/2026 06:10 · nguồn: Seller Centre qua Juli Connector");
  });

  it("price block without a cost: 'chưa có giá vốn' and a way to the import", async () => {
    const p = product();
    const sku = { ...p.cost_and_floor.skus[0]!, cost: { ...p.cost_and_floor.skus[0]!.cost, cogs_per_unit: null }, floor: { ...p.cost_and_floor.skus[0]!.floor!, absolute: null, operating: null, max_discount_pct: null, max_discount_amount: null } };
    page("tab=ng", { ...p, cost_and_floor: { ...p.cost_and_floor, skus: [sku, p.cost_and_floor.skus[1]!] } });
    const price = await screen.findByTestId("sa-price");
    expect(within(price).getByTestId("sa-floor-abs")).toHaveTextContent("chưa có giá vốn");
    expect(within(price).getByTestId("sa-maxdisc")).toHaveTextContent("chưa có");
    expect(within(price).getByRole("link", { name: "Nhập giá vốn ở Cài đặt ›" }).getAttribute("href")).toContain("/settings?");
  });

  it("the Ops view does not offer the cost import", async () => {
    const p = product();
    const sku = { ...p.cost_and_floor.skus[0]!, floor: null };
    page("tab=ng", { ...p, cost_and_floor: { ...p.cost_and_floor, skus: [sku] } }, true);
    const price = await screen.findByTestId("sa-price");
    expect(within(price).queryByRole("link", { name: "Nhập giá vốn ở Cài đặt ›" })).toBeNull();
  });

  it("stock: a stale count, days to sell out and a warning when it is short", async () => {
    page();
    const stock = await screen.findByTestId("sa-stock");
    expect(stock).toHaveTextContent("42");
    expect(stock).toHaveTextContent("Cũ 3 ngày");
    // 60 units over 30 days = 2 / day → 42 / 2 = 21 days
    expect(within(stock).getByTestId("sa-sellout")).toHaveTextContent("còn đủ khoảng 21 ngày");
    expect(stock).toHaveTextContent("số tồn có thể đã đổi");
  });

  it("stock: sắp hết below two weeks", async () => {
    const p = product();
    page("tab=ng", { ...p, header: { ...p.header, stock: { value: 10, age_days: 0, stale: false } } });
    const stock = await screen.findByTestId("sa-stock");
    expect(within(stock).getByTestId("sa-sellout")).toHaveTextContent("sắp hết");
    expect(stock).not.toHaveTextContent("Cũ");
  });

  it("stock: unknown is said, never 0", async () => {
    const p = product();
    page("tab=ng", { ...p, header: { ...p.header, stock: { value: null, age_days: null, stale: false }, missing_fields: ["stock"] } });
    const stock = await screen.findByTestId("sa-stock");
    expect(stock).toHaveTextContent("chưa có");
    expect(stock).toHaveTextContent("Chưa tính được số ngày bán hết");
    expect(screen.getByTestId("sa-missing-fields")).toHaveTextContent("Shopee chưa cung cấp: stock");
  });

  it("reputation block", async () => {
    page();
    const rep = await screen.findByTestId("sa-reputation");
    expect(rep).toHaveTextContent("4,8");
    expect(rep).toHaveTextContent("1.236 đánh giá");
    expect(rep).toHaveTextContent("3.420");
    expect(rep).toHaveTextContent("892");
  });

  it("variations table joins price, orders, margin and floors per SKU and shows the assumed-cost label", async () => {
    page();
    const table = await screen.findByTestId("sa-variations");
    const cb = within(table).getByTestId("sa-var-BEP-S5-CB");
    expect(cb).toHaveTextContent("Cơ bản");
    expect(cb).toHaveTextContent("12,4%");
    expect(cb).toHaveTextContent("181.979đ");
    expect(within(table).getByTestId("sa-var-BEP-S5-QT")).toHaveTextContent("giá vốn giả định (1/3 giá)");
  });

  it("five numbers for the selected period, same labels as Tổng quan", async () => {
    page();
    const box = await screen.findByTestId("sa-sp-five");
    for (const label of ["① % giảm giá", "② Doanh thu thêm / chi thêm", "③ Biên lợi nhuận cuối", "④ Số đơn", "⑤ AOV"]) {
      expect(box).toHaveTextContent(label);
    }
    expect(within(box).getByTestId("sa-sp-five-bien")).toHaveTextContent("= 1.400.000đ lợi nhuận");
  });

  it("back link and banner follow where the person came from", async () => {
    page("tab=ng&kpi=bien&src=voucher&row=v5&from=ranking");
    expect(await screen.findByTestId("sa-from-banner")).toHaveTextContent("Mở từ Xếp hạng · Biên cuối × Voucher · dòng v5");
    const back = screen.getByRole("link", { name: "‹ Xếp hạng" });
    expect(Object.fromEntries(q(back.getAttribute("href")))).toEqual({ kpi: "bien", src: "voucher", focus: "v5" });
  });

  it("a Thẻ sản phẩm child in the banner is named", async () => {
    page("tab=ng&kpi=ctor&src=the_san_pham&sub=de_xuat&row=GL-001&from=ranking");
    expect(await screen.findByTestId("sa-from-banner")).toHaveTextContent("Mở từ Xếp hạng · CTOR × Đề xuất · dòng GL-001");
  });

  it("an unknown product is its own state", async () => {
    renderWith(<ProductPageView id="NOPE" params={params()} />, fakeApi({}, new ShopeeApiError(404, "product_not_found", "x")));
    expect(await screen.findByTestId("sa-refusal-not-found")).toHaveTextContent("Không tìm thấy sản phẩm này");
  });

  it("never draws a buyer field", async () => {
    const { container } = page();
    await screen.findByTestId("sa-hero");
    expect(textOf(container).toLowerCase()).not.toContain("buyer");
  });
});

describe("Sản phẩm: tabs", () => {
  it("the five tabs are links that keep kpi, src, sub, row and from", async () => {
    page("tab=ng&kpi=ctor&src=the_san_pham&sub=de_xuat&row=GL-001&from=ranking");
    const tabs = await screen.findByRole("tablist", { name: "Sản phẩm" });
    for (const name of ["Hiệu suất", "Nguồn", "Từ khoá", "Chi phí & giá sàn", "Lịch sử"]) {
      expect(within(tabs).getByRole("link", { name })).toBeInTheDocument();
    }
    const kw = within(tabs).getByRole("link", { name: "Từ khoá" });
    expect(Object.fromEntries(q(kw.getAttribute("href")))).toEqual({ tab: "kw", kpi: "ctor", src: "the_san_pham", sub: "de_xuat", row: "GL-001", from: "ranking" });
    expect(within(tabs).getByRole("link", { name: "Nguồn" })).toHaveAttribute("aria-current", "true");
  });

  it("Hiệu suất: the chain by period, with period links and an honest note about the daily series", async () => {
    page("tab=hs");
    const tab = await screen.findByTestId("sa-tab-hs");
    expect(tab).toHaveTextContent("Lượt xem");
    expect(tab).toHaveTextContent("7.500");
    expect(tab).toHaveTextContent("4,67%");
    expect(tab).toHaveTextContent("10,00%");
    expect(tab).toHaveTextContent("7.000.000đ");
    expect(q(within(tab).getByRole("link", { name: "7 ngày" }).getAttribute("href")).get("ky")).toBe("7d");
    expect(within(tab).getByTestId("sa-no-daily")).toHaveTextContent("Chuỗi theo ngày");
  });

  it("Nguồn: five flows when the product has the Trang shop split", async () => {
    page("tab=ng");
    const tab = await screen.findByTestId("sa-tab-ng");
    for (const key of ["the_san_pham_khac", "trang_shop", "live", "video", "lien_ket"]) {
      expect(within(tab).getByTestId(`sa-ng-flow-${key}`)).toBeInTheDocument();
    }
    expect(within(tab).queryByTestId("sa-four-flows")).toBeNull();
    expect(tab).toHaveTextContent("35 đơn · 100,0%");
  });

  it("Nguồn: four flows with the trang_shop_available: false note when there is no Trang shop split", async () => {
    const p = product();
    const flows = matrixProduct("X", { flows: { ...matrixProduct("X").flows!, trang_shop_available: false, rows: matrixProduct("X").flows!.rows.filter((r) => r.key !== "trang_shop") } }).flows;
    page("tab=ng", { ...p, nguon: { ...p.nguon, flows } });
    const tab = await screen.findByTestId("sa-tab-ng");
    expect(within(tab).queryByTestId("sa-ng-flow-trang_shop")).toBeNull();
    expect(within(tab).getByTestId("sa-four-flows")).toHaveTextContent("trang_shop_available: false");
  });

  it("Nguồn: item_traffic_sources present means five flows", async () => {
    const p = product();
    const flows = matrixProduct("X", { flows: { ...matrixProduct("X").flows!, trang_shop_available: false } }).flows;
    page("tab=ng", { ...p, nguon: { ...p.nguon, flows }, item_traffic_sources: [{ item_id: "BEP-S5" }] });
    expect(within(await screen.findByTestId("sa-tab-ng")).queryByTestId("sa-four-flows")).toBeNull();
  });

  it("Nguồn: the four price levers and the ads overlay with its placed-order label (hideable)", async () => {
    page("tab=ng");
    const user = userEvent.setup();
    const tab = await screen.findByTestId("sa-tab-ng");
    for (const key of ["khong_uu_dai", "voucher", "khuyen_mai", "combo"]) {
      expect(within(tab).getByTestId(`sa-ng-lever-${key}`)).toBeInTheDocument();
    }
    const ads = within(tab).getByTestId("sa-ng-ads");
    expect(ads).toHaveTextContent("đơn đã đặt");
    expect(ads).toHaveTextContent("Không cộng thêm vào tổng".replace("Không cộng thêm vào tổng", "không cộng thêm vào tổng"));
    await user.click(within(tab).getByRole("button", { name: "Ẩn lớp Quảng cáo" }));
    expect(within(tab).queryByTestId("sa-ng-ads")).toBeNull();
  });

  it("Nguồn: a flow row opens the Xếp hạng of that source for this product", async () => {
    page("tab=ng");
    const live = await screen.findByTestId("sa-ng-flow-live");
    const href = within(live).getAllByRole("link")[0]!.getAttribute("href");
    expect(Object.fromEntries(q(href))).toEqual({ kpi: "gmv", src: "live", focus: "BEP-S5", from: "san-pham" });
  });

  it("Nguồn: no flow data at all is said", async () => {
    const p = product();
    page("tab=ng", { ...p, nguon: { ...p.nguon, flows: null } });
    expect(await screen.findByTestId("sa-ng-noflows")).toBeInTheDocument();
  });

  it("Từ khoá: at 5/5 the limit message shows; roles, volume, title position and excluded words", async () => {
    page("tab=kw");
    const tab = await screen.findByTestId("sa-tab-kw");
    expect(tab).toHaveTextContent("5/5 chính");
    expect(within(tab).getByTestId("sa-kw-limit")).toHaveTextContent("Đã đủ 5 từ khoá chính.");
    expect(within(tab).getByTestId("sa-kw-bộ vệ sinh bếp")).toHaveTextContent("Chính");
    expect(within(tab).getByTestId("sa-kw-bộ vệ sinh bếp")).toHaveTextContent("1.000");
    expect(within(tab).getByTestId("sa-kw-xơ mướp")).toHaveTextContent("không có trong tiêu đề");
    expect(within(tab).getByTestId("sa-kw-dụng cụ bếp")).toHaveTextContent("Phụ");
    expect(within(tab).getByTestId("sa-kw-dụng cụ bếp")).toHaveTextContent("chi 100.000đ · 2 đơn (đơn đã đặt)");
    expect(within(tab).getByTestId("sa-kw-cover")).toHaveTextContent("3/5 · 60%");
    expect(within(tab).getByTestId("sa-kw-excluded")).toHaveTextContent("− cũ");
  });

  it("Từ khoá: below the limit there is no limit message; with no keywords the empty state shows", async () => {
    const p = product();
    page("tab=kw", { ...p, keywords: { ...p.keywords, core: { ...p.keywords.core, used: 4, full: false } } });
    expect(within(await screen.findByTestId("sa-tab-kw")).queryByTestId("sa-kw-limit")).toBeNull();
  });

  it("Từ khoá: empty", async () => {
    const p = product();
    page("tab=kw", {
      ...p,
      keywords: { roles: { chinh: { label: "Chính", keywords: [] }, phu: { label: "Phụ", keywords: [] }, thuong_hieu: { label: "Thương hiệu", keywords: [] }, loai_tru: { label: "Loại trừ", keywords: [] } }, core: { used: 0, max: 5, full: false, in_title: 0, coverage_pct: null }, title_counted_chars: 100 },
    });
    expect(await screen.findByTestId("sa-kw-empty")).toBeInTheDocument();
  });

  it("Chi phí & giá sàn: per-unit waterfall, both floors with their formulas, max discount and an OK verdict", async () => {
    page("tab=cp");
    const tab = await screen.findByTestId("sa-tab-cp");
    const wf = within(tab).getByTestId("sa-waterfall");
    expect(wf).toHaveTextContent("Giá niêm yết200.000đ");
    expect(wf).toHaveTextContent("− Voucher shop10.000đ");
    expect(wf).toHaveTextContent("= Khách trả (doanh thu thực)190.000đ");
    expect(wf).toHaveTextContent("− Phí sàn28.500đ");
    expect(wf).toHaveTextContent("− Giá vốn100.000đ");
    expect(wf).toHaveTextContent("= Lợi nhuận23.500đ");
    expect(wf).toHaveTextContent("Biên lợi nhuận12,4%");
    expect(tab).toHaveTextContent("121.176đ");
    expect(tab).toHaveTextContent("181.979đ");
    expect(tab).toHaveTextContent("9,0% · 18.000đ");
    expect(tab).toHaveTextContent("(giá vốn + đóng gói + phí cố định) ÷ (1 − phí sàn)");
    expect(within(tab).getByTestId("sa-verdict")).toHaveTextContent("cao hơn giá sàn vận hành 8.021đ");
    expect(within(tab).getByTestId("sa-gauge")).toBeInTheDocument();
    expect(within(tab).queryByTestId("sa-assumed-cost")).toBeNull();
  });

  it("Chi phí & giá sàn: an assumed cost is labelled 'giá vốn giả định (1/3 giá)'", async () => {
    page("tab=cp");
    const user = userEvent.setup();
    const tab = await screen.findByTestId("sa-tab-cp");
    await user.click(within(tab).getByRole("button", { name: "BEP-S5-QT" }));
    expect(within(tab).getByTestId("sa-assumed-cost")).toHaveTextContent("giá vốn giả định (1/3 giá)");
    expect(within(tab).getByTestId("sa-assumed-cost")).toHaveTextContent("33.333đ/sản phẩm");
  });

  it("Chi phí & giá sàn: a breach turns the verdict red", async () => {
    const p = product();
    const s = p.cost_and_floor.skus[0]!;
    page("tab=cp", { ...p, cost_and_floor: { ...p.cost_and_floor, skus: [{ ...s, floor: { ...s.floor!, net_revenue_per_unit: 170_000, breach: "operating" } }] } });
    const verdict = await screen.findByTestId("sa-verdict");
    expect(verdict.className).toContain("sa-verdict--bad");
    expect(verdict).toHaveTextContent("thấp hơn giá sàn vận hành 11.979đ");
  });

  it("Chi phí & giá sàn: a SKU with no cost shows the empty state pointing to Cài đặt", async () => {
    const p = product();
    const s = p.cost_and_floor.skus[0]!;
    page("tab=cp", { ...p, cost_and_floor: { ...p.cost_and_floor, skus: [{ ...s, cost: { ...s.cost, cogs_per_unit: null, label: null }, floor: { ...s.floor!, absolute: null, operating: null } }] } });
    const none = await screen.findByTestId("sa-nocost");
    expect(none).toHaveTextContent("Chưa có giá vốn cho BEP-S5-CB");
    expect(within(none).getByRole("link", { name: "Nhập giá vốn ở Cài đặt ›" }).getAttribute("href")).toContain("sku=BEP-S5-CB");
  });

  it("Chi phí & giá sàn: no order lines says so", async () => {
    const p = product();
    page("tab=cp", { ...p, cost_and_floor: { ...p.cost_and_floor, skus: [] } });
    expect(await screen.findByTestId("sa-cp-empty")).toBeInTheDocument();
  });

  it("Lịch sử: empty state when the backend has no events", async () => {
    page("tab=ls");
    expect(await screen.findByTestId("sa-history-empty")).toHaveTextContent("Chưa có lịch sử cho sản phẩm này");
  });

  it("Lịch sử: card events and detected changes, with the filter", async () => {
    const p = product();
    page("tab=ls", {
      ...p,
      history: [
        { at: "2026-11-02T08:00:00Z", type: "card", title: "Thẻ đã thực hiện: voucher 10.000đ", detail: "T+7: +12% đơn" },
        { at: "2026-10-30T08:00:00Z", type: "change", title: "Giá niêm yết đổi", before: "139.000đ", after: "129.000đ" },
      ],
    });
    const user = userEvent.setup();
    const tab = await screen.findByTestId("sa-tab-ls");
    expect(tab).toHaveTextContent("Thẻ đã thực hiện: voucher 10.000đ");
    expect(tab).toHaveTextContent("139.000đ");
    expect(tab).toHaveTextContent("129.000đ");
    await user.click(within(tab).getByRole("button", { name: "Thay đổi phát hiện" }));
    expect(tab).not.toHaveTextContent("Thẻ đã thực hiện");
    expect(tab).toHaveTextContent("Giá niêm yết đổi");
  });
});

describe("Sản phẩm: list", () => {
  it("lists products by GMV, each opening its page", async () => {
    renderWith(<ProductListView params={params()} />, fakeApi());
    const rows = await screen.findByTestId("sa-product-rows");
    const first = within(rows).getAllByRole("link")[0]!;
    expect(first).toHaveTextContent("Bộ vệ sinh bếp 5 món");
    expect(first).toHaveTextContent("12.000.000đ");
    expect(first.getAttribute("href")).toBe("/san-pham/BEP-S5?tab=hs&from=san-pham");
  });

  it("empty", async () => {
    renderWith(<ProductListView params={params()} />, fakeApi({ matrix: matrix({ products: [], product_count: 0 }) }));
    await waitFor(() => expect(screen.getByTestId("sa-product-empty")).toBeInTheDocument());
  });
});
