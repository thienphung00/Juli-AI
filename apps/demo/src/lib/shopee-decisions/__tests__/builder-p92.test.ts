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

  it("combo needs 2-6 distinct products", () => {
    const f = initialForms();
    expect(buildVersion("combo", f, ctx).problem).toMatch(/2 đến 6/);
    const same = { ...f, combo: { ...f.combo, items: [{ itemId: P_ZIP, variationId: "", qty: "1" }, { itemId: P_ZIP, variationId: "", qty: "1" }] } };
    expect(buildVersion("combo", same, ctx).problem).toMatch(/khác nhau/);
    const ok = { ...f, combo: { ...f.combo, items: [{ itemId: P_ZIP, variationId: "v3", qty: "1" }, { itemId: P_SPONGE, variationId: "", qty: "2" }] } };
    expect(buildVersion("combo", ok, ctx).version).toMatchObject({ kind: "combo", items: [{ item_id: P_ZIP, variation_id: "v3", qty: 1 }, { item_id: P_SPONGE, variation_id: "", qty: 2 }], pricing: "pct", value: 10 });
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
