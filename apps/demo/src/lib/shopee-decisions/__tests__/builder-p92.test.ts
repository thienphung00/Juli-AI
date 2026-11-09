import { describe, expect, it } from "vitest";

import { P_SPONGE, P_ZIP, pickerProducts, variationList } from "./builder-fixtures";
import { bandText, breakEvenText, buildVersion, initialForms, kmoney, num, voucherChips } from "../builder-p92";
import { outcome } from "./builder-fixtures";

const ctx = { product: pickerProducts().products[0]!, variations: variationList().variations.slice(0, 2) };

describe("builder-p92 model", () => {
  it("parses typed numbers", () => {
    expect(num("5000")).toBe(5000);
    expect(num(" 12,5 ")).toBe(12.5);
    expect(num("")).toBeNull();
    expect(num("abc")).toBeNull();
    expect(kmoney(5000)).toBe("5k");
    expect(kmoney(12500)).toBe("12.500đ");
  });

  it("voucher chips come from the AOV: 5k/100k, 10k/100k, 10k/150k, 15k/200k at 124.143đ", () => {
    expect(voucherChips(124_143).map((c) => c.label)).toEqual(["5k / 100k", "10k / 100k", "10k / 150k", "15k / 200k"]);
    expect(voucherChips(null)[0]).toMatchObject({ value: 5000, min: 100_000 });
    expect(voucherChips(300_000)[0]!.min).toBe(250_000);
  });

  it("voucher: 5k / 100k and 10k / 100k are two versions of the same kind; 0đ minimum is allowed; pct is capped at 90", () => {
    const f = initialForms();
    const a = buildVersion("voucher", { ...f, voucher: { ...f.voucher, value: "5000", min: "100000" } }, ctx);
    const b = buildVersion("voucher", { ...f, voucher: { ...f.voucher, value: "10000", min: "100000" } }, ctx);
    expect(a.version).toMatchObject({ kind: "voucher", scope: "product", item_ids: [P_ZIP], value: 5000, min_spend: 100000, label: "5k / 100k" });
    expect(b.version).toMatchObject({ value: 10000 });
    expect(buildVersion("voucher", { ...f, voucher: { ...f.voucher, min: "0" } }, ctx).version).toMatchObject({ min_spend: 0 });
    expect(buildVersion("voucher", { ...f, voucher: { ...f.voucher, dtype: "pct", value: "95" } }, ctx).problem).toMatch(/90%/);
    expect(buildVersion("voucher", { ...f, voucher: { ...f.voucher, scope: "shop" } }, ctx).version).not.toHaveProperty("item_ids");
  });

  it("combo (P97 D85.15): a product list, tiers 'Mua N', Shopee's limits, no per-item quantity or variation", () => {
    const f = initialForms();
    expect(buildVersion("combo", f, ctx).problem).toMatch(/ít nhất một sản phẩm/);
    const ok = { ...f, combo: { ...f.combo, name: "Mua 2 giảm 5", items: [P_ZIP, P_SPONGE], limit: "3" } };
    const v = buildVersion("combo", ok, ctx).version as unknown as Record<string, unknown>;
    expect(v).toMatchObject({ kind: "combo", name: "Mua 2 giảm 5", item_ids: [P_ZIP, P_SPONGE], discount_type: "pct", tiers: [{ qty: 2, value: 5 }, { qty: 3, value: 8 }], purchase_limit: 3 });
    expect(v).not.toHaveProperty("items");
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, name: "x".repeat(26) } }, ctx).problem).toMatch(/25 ký tự/);
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, tiers: [{ qty: "2", value: "5" }, { qty: "2", value: "9" }] } }, ctx).problem).toMatch(/khác nhau/);
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, tiers: [{ qty: "1", value: "5" }] } }, ctx).problem).toMatch(/từ 2 đến 9999/);
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, tiers: [{ qty: "2", value: "95" }] } }, ctx).problem).toMatch(/tối đa 90%/);
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, dtype: "special_price", tiers: [{ qty: "2", value: "10" }] } }, ctx).problem).toMatch(/quá thấp/);
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, tiers: [] } }, ctx).problem).toMatch(/ít nhất một mức/);
    expect(buildVersion("combo", { ...ok, combo: { ...ok.combo, limit: "0" } }, ctx).problem).toMatch(/Giới hạn đặt hàng/);
  });

  it("listing combo (P97 D85.16): a title, a price, stock and at least two member products", () => {
    const f = initialForms();
    expect(buildVersion("listing_combo", f, ctx).problem).toMatch(/tên listing combo/);
    const base = { ...f, listing_combo: { ...f.listing_combo, title: "Combo túi zip + miếng rửa", price: "120000", stock: "50", sku: "CB-01", images: ["a.jpg"], members: [P_ZIP, P_SPONGE] } };
    expect(buildVersion("listing_combo", base, ctx).version).toMatchObject({ kind: "listing_combo", title: "Combo túi zip + miếng rửa", price: 120000, stock: 50, sku: "CB-01", image_refs: ["a.jpg"], member_ids: [P_ZIP, P_SPONGE] });
    expect(buildVersion("listing_combo", { ...base, listing_combo: { ...base.listing_combo, members: [P_ZIP] } }, ctx).problem).toMatch(/từ 2 sản phẩm/);
    expect(buildVersion("listing_combo", { ...base, listing_combo: { ...base.listing_combo, price: "10" } }, ctx).problem).toMatch(/từ 1.000đ/);
    expect(buildVersion("listing_combo", { ...base, listing_combo: { ...base.listing_combo, stock: "" } }, ctx).problem).toMatch(/tồn kho/);
  });

  it("title and first line keep their limits", () => {
    const f = initialForms();
    expect(buildVersion("title", { ...f, title: { ticked: [], text: "x".repeat(101) } }, ctx).problem).toMatch(/100/);
    expect(buildVersion("title", { ...f, title: { ticked: ["a"], text: "Túi zip" } }, ctx).version).toMatchObject({ kind: "title", title: "Túi zip", keywords: ["a"] });
    expect(buildVersion("description_first_line", { ...f, description_first_line: { text: "a\nb" } }, ctx).problem).toMatch(/xuống dòng/);
  });

  it("price + flash sale choose the server kind", () => {
    const f = initialForms();
    const rows = [{ variationId: "v3", value: "75000" }];
    expect(buildVersion("price_flash", { ...f, price_flash: { ...f.price_flash, what: "price", mode: "final_price", rows } }, ctx).version).toMatchObject({ kind: "price", variations: [{ variation_id: "v3", final_price: 75000 }] });
    expect(buildVersion("price_flash", { ...f, price_flash: { ...f.price_flash, what: "flash_sale", mode: "final_price", rows } }, ctx).version).toMatchObject({ kind: "flash_sale", units: 50 });
  });

  it("reads an outcome: bands, break-even in orders and CTOR, insufficient data", () => {
    expect(bandText({ low: -157_000, p50: 54_000, high: 282_000 })).toEqual({ main: "+54.000đ", range: "−157.000đ – +282.000đ" });
    expect(bandText(null)).toEqual({ main: "—", range: "không đủ dữ liệu" });
    expect(bandText({ low: 8, p50: 16, high: 25 }, "orders")).toEqual({ main: "+16 đơn", range: "+8 – +25" });
    expect(breakEvenText(outcome())).toBe("cần thêm ≥ 18 đơn, tức CTOR ≥ 2,71% (hôm nay 2,50%), để lợi nhuận không giảm.");
    expect(breakEvenText(outcome(0, { break_even: { applies: false, extra_orders: null, ctor_now: null, ctor_needed: null, reason: "Không có chi phí trực tiếp." } }))).toBe("Không có chi phí trực tiếp.");
  });
});


describe("beforeAfterText (So sánh, D85.9)", () => {
  const base = { label: "AOV", unit: "vnd" as const, unchanged: false, reason: null };
  it("shows before -> P50 with the P10 - P90 range", async () => {
    const { beforeAfterText } = await import("../builder-p92");
    const t = beforeAfterText({ ...base, key: "aov", before: 150_000, after: { low: 152_000, p50: 158_000, high: 165_000 } });
    expect(t.main).toContain("→");
    expect(t.range).toContain("–");
    expect(t.unchanged).toBe(false);
  });
  it("says không đổi with the reason and never a lift", async () => {
    const { beforeAfterText } = await import("../builder-p92");
    const t = beforeAfterText({ ...base, key: "views", label: "Lượt xem", unit: "count", before: 1000, after: { low: 1000, p50: 1000, high: 1000 }, unchanged: true, reason: "Mô hình không dự kiến thay đổi Lượt xem (không bịa mức tăng)." });
    expect(t.main).toContain("không đổi");
    expect(t.main).not.toContain("→");
    expect(t.range).toContain("không bịa");
  });
});
