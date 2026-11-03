import { describe, expect, it } from "vitest";

import { opsTabShopeeLinks, sellerLinks, viewAsShopeeLinks } from "../links";
import { apiRankingArgs, defaultKind, readRanking, readWindow, windowParams } from "../params";

const q = (href: string) => new URLSearchParams(href.split("?")[1] ?? "");
const path = (href: string) => href.split("?")[0];

describe("link parameters follow the VERIFY.md table", () => {
  it("Tổng quan tile / matrix cell → Xếp hạng: kpi, src, from", () => {
    const href = sellerLinks.ranking({ kpi: "aov", src: "ads", from: "tong-quan" });
    expect(path(href)).toBe("/xep-hang");
    expect([...q(href).entries()]).toEqual([
      ["kpi", "aov"],
      ["src", "ads"],
      ["from", "tong-quan"],
    ]);
  });

  it("Thẻ sản phẩm child → Xếp hạng: kpi, src, sub, from", () => {
    const p = q(sellerLinks.ranking({ kpi: "aov", src: "the_san_pham", sub: "de_xuat", from: "tong-quan" }));
    expect(p.get("sub")).toBe("de_xuat");
    expect(p.get("src")).toBe("the_san_pham");
  });

  it("Tổng quan → Sản phẩm: id in the path, tab, from", () => {
    const href = sellerLinks.product("BEP-S5", { tab: "ng", from: "tong-quan" });
    expect(path(href)).toBe("/san-pham/BEP-S5");
    expect(q(href).get("tab")).toBe("ng");
    expect(q(href).get("from")).toBe("tong-quan");
  });

  it("Xếp hạng 'Mở sản phẩm ›' → Sản phẩm: tab, kpi, src, sub, row, from", () => {
    const href = sellerLinks.product("BEP-S5", { tab: "ng", kpi: "ctor", src: "the_san_pham", sub: "de_xuat", row: "GL-001", from: "ranking" });
    expect(Object.fromEntries(q(href))).toEqual({ tab: "ng", kpi: "ctor", src: "the_san_pham", sub: "de_xuat", row: "GL-001", from: "ranking" });
  });

  it("Phân tích → Xếp hạng: kpi, src, focus, from, card", () => {
    const href = sellerLinks.ranking({ kpi: "bien", src: "all", focus: "TU-004", from: "phan-tich", card: "c_tu_price" });
    expect(Object.fromEntries(q(href))).toEqual({ kpi: "bien", src: "all", focus: "TU-004", from: "phan-tich", card: "c_tu_price" });
  });

  it("→ đề xuất goes to the card id with where it came from", () => {
    const href = sellerLinks.card("c_bep_ads", "tong-quan");
    expect(path(href)).toBe("/decisions");
    expect(Object.fromEntries(q(href))).toEqual({ the: "c_bep_ads", from: "tong-quan" });
  });

  it("carries the window to the next screen and leaves the default out", () => {
    const w = readWindow(new URLSearchParams("ky=thang&thang=2026-10"));
    const href = sellerLinks.ranking({ kpi: "gmv", src: "all", from: "tong-quan" }, w);
    expect(q(href).get("ky")).toBe("thang");
    expect(q(href).get("thang")).toBe("2026-10");
    expect(q(sellerLinks.overview(readWindow(new URLSearchParams()))).toString()).toBe("");
  });

  it("view-as links stay inside the view-as page", () => {
    const l = viewAsShopeeLinks("shop-1");
    const href = l.product("BEP-S5", { tab: "ng", from: "tong-quan" });
    expect(path(href)).toBe("/ops/shops/shop-1/xem");
    expect(q(href).get("trang")).toBe("san-pham");
    expect(q(href).get("id")).toBe("BEP-S5");
    expect(q(l.ranking({ kpi: "gmv" })).get("trang")).toBe("xep-hang");
    expect(q(l.overview()).get("trang")).toBe("tong-quan");
  });

  it("the Ops tab links use ?man=", () => {
    const l = opsTabShopeeLinks("shop-1");
    const href = l.ranking({ kpi: "ctr", src: "live", from: "tong-quan" });
    expect(path(href)).toBe("/ops/shops/shop-1/shopee/phan-tich");
    expect(q(href).get("man")).toBe("xep-hang");
    expect(q(href).get("kpi")).toBe("ctr");
  });
});

describe("window and ranking state from the URL", () => {
  it("defaults to 30 days with comparison on", () => {
    const w = readWindow(new URLSearchParams());
    expect(w.query).toEqual({ period: "30d" });
    expect(w.compare).toBe(true);
  });

  it("reads a month, a custom window and the compare switch", () => {
    expect(readWindow(new URLSearchParams("ky=thang&thang=2026-10")).query).toEqual({ period: "month", month: "2026-10" });
    expect(readWindow(new URLSearchParams("ky=tuy-chon&tu=2026-10-01&den=2026-10-20")).query).toEqual({ period: "custom", from: "2026-10-01", to: "2026-10-20" });
    expect(readWindow(new URLSearchParams("cmp=0")).compare).toBe(false);
  });

  it("falls back to 30 days for an incomplete month or window", () => {
    expect(readWindow(new URLSearchParams("ky=thang")).query).toEqual({ period: "30d" });
    expect(readWindow(new URLSearchParams("ky=tuy-chon&tu=2026-10-01")).query).toEqual({ period: "30d" });
    expect(readWindow(new URLSearchParams("ky=thang&thang=oops")).query).toEqual({ period: "30d" });
  });

  it("round-trips the window parameters", () => {
    const w = readWindow(new URLSearchParams("ky=tuy-chon&tu=2026-10-01&den=2026-10-20&cmp=0"));
    expect(windowParams(w).toString()).toBe("ky=tuy-chon&tu=2026-10-01&den=2026-10-20&cmp=0");
  });

  it("maps the artboard's source keys to the API's", () => {
    const s = readRanking(new URLSearchParams("kpi=ctor&src=the_san_pham&sub=de_xuat&focus=XM-003&from=card&card=c_xm_disc"));
    expect(apiRankingArgs(s)).toEqual({ kind: "products", source: "the_san_pham_khac", sub: "recommend", xepTheo: "gmv_per_day" });
    expect(s.focus).toBe("XM-003");
    expect(s.card).toBe("c_xm_disc");
  });

  it("row kinds follow the source", () => {
    expect(defaultKind("gmv", "ads", null)).toBe("campaigns");
    expect(defaultKind("gmv", "lien_ket", null)).toBe("kols");
    expect(defaultKind("aov", "lien_ket", null)).toBe("products");
    expect(defaultKind("ctor", "voucher", null)).toBe("vouchers");
    expect(defaultKind("views", "the_san_pham", "search")).toBe("keywords");
    expect(defaultKind("ctr", "all", null)).toBe("products");
    expect(apiRankingArgs(readRanking(new URLSearchParams("kpi=gmv&src=ads")))).toMatchObject({ kind: "campaigns", source: "ads" });
    expect(apiRankingArgs(readRanking(new URLSearchParams("kpi=ctor&src=voucher")))).toMatchObject({ kind: "vouchers", source: "voucher" });
  });

  it("ignores unknown kpi / source / sub", () => {
    const s = readRanking(new URLSearchParams("kpi=zzz&src=zzz&sub=zzz"));
    expect(s.kpi).toBe("gmv");
    expect(s.src).toBe("all");
    expect(s.sub).toBeNull();
  });

  it("maps 'Xếp theo' to xep_theo", () => {
    expect(apiRankingArgs(readRanking(new URLSearchParams("xep=profit"))).xepTheo).toBe("profit_per_day");
    expect(apiRankingArgs(readRanking(new URLSearchParams("xep=disc"))).xepTheo).toBe("giam_gia");
  });
});
