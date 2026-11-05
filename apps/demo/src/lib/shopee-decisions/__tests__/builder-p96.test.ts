import { describe, expect, it } from "vitest";

import { createBuilderApi, type VariationRow } from "../builder-api";
import { breakEvenText, buildVersion, defaultVariationId, initialForms, refusalText, unitLines, type Forms } from "../builder-p92";
import { outcome, pickerProducts, variationList } from "./builder-fixtures";

/** P96 (2026-11-05 ORY sweep): the builder refuses in Vietnamese what the server would 422, never prints codes. */

const product = pickerProducts().products[0]!;
const ctx = { product, variations: variationList().variations.slice(0, 2) };
const f = initialForms();
const problem = (kind: Parameters<typeof buildVersion>[0], forms: Forms, c = ctx) => buildVersion(kind, forms, c).problem;

describe("P96 · client limits match the server (A2, B3, E2, D3, E6)", () => {
  it("voucher: per-buyer 0, cap 0, usage 0, end before start, > 90 days and value ≥ minimum are refused", () => {
    const v = f.voucher;
    expect(problem("voucher", { ...f, voucher: { ...v, perBuyer: "0" } })).toMatch(/Giới hạn mỗi người/);
    expect(problem("voucher", { ...f, voucher: { ...v, dtype: "pct", value: "10", max: "0" } })).toMatch(/Giảm tối đa/);
    expect(problem("voucher", { ...f, voucher: { ...v, usage: "0" } })).toMatch(/Số lượt dùng tối đa/);
    expect(problem("voucher", { ...f, voucher: { ...v, start: "2026-11-20", end: "2026-11-10" } })).toMatch(/kết thúc/);
    expect(problem("voucher", { ...f, voucher: { ...v, start: "2026-11-10", end: "2027-11-10" } })).toMatch(/90 ngày/);
    expect(problem("voucher", { ...f, voucher: { ...v, value: "150000", min: "100000" } })).toMatch(/nhỏ hơn đơn tối thiểu/);
    // Past dates stay allowed (owner, 2026-11-05).
    expect(buildVersion("voucher", { ...f, voucher: { ...v, start: "2026-10-01", end: "2026-10-05" } }, ctx).version).toMatchObject({ start: "2026-10-01", end: "2026-10-05" });
  });

  it("percent above 90 is refused for add-on, product discount and flash sale (the server caps them at 90)", () => {
    const addon = { itemId: "p2", variationId: "", mode: "pct" as const, value: "95", limit: "1" };
    expect(problem("add_on", { ...f, add_on: { addons: [addon] } })).toMatch(/tối đa 90%/);
    expect(problem("product_discount", { ...f, product_discount: { ...f.product_discount, rows: [{ variationId: "v3", value: "95" }] } })).toMatch(/tối đa 90%/);
    expect(problem("price_flash", { ...f, price_flash: { ...f.price_flash, what: "flash_sale", rows: [{ variationId: "v3", value: "95" }] } })).toMatch(/tối đa 90%/);
    expect(problem("combo", { ...f, combo: { ...f.combo, items: [{ itemId: "a", variationId: "", qty: "1" }, { itemId: "b", variationId: "", qty: "1" }], value: "95" } })).toMatch(/tối đa 90%/);
  });

  it("0 is refused, not clamped to 1: gift qty, add-on limit, pack count, per-buyer of a discount, flash hours", () => {
    expect(problem("gift", { ...f, gift: { ...f.gift, giftItemId: "p2", qty: "0" } })).toMatch(/Số lượng quà/);
    const addon = { itemId: "p2", variationId: "", mode: "pct" as const, value: "15", limit: "0" };
    expect(problem("add_on", { ...f, add_on: { addons: [addon] } })).toMatch(/Giới hạn mỗi đơn/);
    expect(problem("variation_set", { ...f, variation_set: { rows: [{ name: "Set 3", price: "270000", sku: "", packCount: "0", stock: "" }] } })).toMatch(/Số lượng trong gói/);
    expect(problem("product_discount", { ...f, product_discount: { ...f.product_discount, rows: [{ variationId: "v3", value: "10" }], perBuyer: "0" } })).toMatch(/Giới hạn mỗi người/);
    expect(problem("price_flash", { ...f, price_flash: { ...f.price_flash, what: "flash_sale", rows: [{ variationId: "v3", value: "10" }], slotHours: "0" } })).toMatch(/Số giờ/);
  });

  it("a gift that is not sold needs a name", () => {
    const g = { ...f.gift, source: "unsold" as const, unitCost: "10000", label: "" };
    expect(problem("gift", { ...f, gift: g })).toBe("Nhập tên quà.");
    expect(buildVersion("gift", { ...f, gift: { ...g, label: "Túi vải" } }, ctx).version).toMatchObject({ gift: { label: "Túi vải" } });
  });
});

describe("P96 · price change (G2, G3)", () => {
  it("0 % and the current price are 'Giá không đổi.'; + raises the price", () => {
    const p = f.price_flash;
    expect(problem("price_flash", { ...f, price_flash: { ...p, rows: [{ variationId: "v3", value: "0" }] } })).toBe("Giá không đổi.");
    expect(problem("price_flash", { ...f, price_flash: { ...p, mode: "final_price", rows: [{ variationId: "v3", value: "87000" }] } })).toBe("Giá không đổi.");
    expect(buildVersion("price_flash", { ...f, price_flash: { ...p, rows: [{ variationId: "v3", value: "5" }] } }, ctx).version).toMatchObject({ kind: "price", variations: [{ variation_id: "v3", change_pct: 5 }] });
  });

  it("an out-of-range change shows its message (G4)", () => {
    expect(problem("price_flash", { ...f, price_flash: { ...f.price_flash, rows: [{ variationId: "v3", value: "200" }] } })).toMatch(/−50% đến \+100%/);
  });
});

describe("P96 · no code is ever shown (A2, E4, I6, C1)", () => {
  it("a pydantic 422 list reads as 'Thông số chưa hợp lệ: <field>' and other statuses never as a bare 'HTTP n'", async () => {
    const body = { detail: [{ type: "greater_than_equal", loc: ["body", "versions", 0, "voucher", "per_buyer_limit"], msg: "Input should be greater than or equal to 1", input: 0 }] };
    const api = createBuilderApi({ base: "/x", token: "t", fetchImpl: async () => new Response(JSON.stringify(body), { status: 422, headers: { "Content-Type": "application/json" } }) });
    await expect(api.evaluate([])).rejects.toThrow("Thông số chưa hợp lệ: Giới hạn mỗi người.");
    const bare = createBuilderApi({ base: "/x", token: "t", fetchImpl: async () => new Response("{}", { status: 502, headers: { "Content-Type": "application/json" } }) });
    await expect(bare.evaluate([])).rejects.toThrow(/lỗi 502/);
    await expect(bare.evaluate([])).rejects.not.toThrow(/^HTTP/);
  });

  it("break-even and CTOR reasons read in Vietnamese; a server reason_text wins", () => {
    expect(breakEvenText(outcome(0, { break_even: { applies: false, extra_orders: null, ctor_now: null, ctor_needed: null, reason: "not_applicable" } }))).toBe("Không có chi phí trực tiếp; đo sau khi chạy.");
    const noClicks = breakEvenText(outcome(0, { break_even: { applies: true, extra_orders: 61, ctor_now: null, ctor_needed: null, ctor_reason: "no_clicks" } }));
    expect(noClicks).not.toMatch(/no_clicks/);
    expect(noClicks).toMatch(/chưa có lượt nhấp/);
    expect(breakEvenText(outcome(0, { break_even: { applies: false, extra_orders: null, ctor_now: null, ctor_needed: null, reason: "x_y", reason_text: "Câu của server." } }))).toBe("Câu của server.");
    expect(breakEvenText(outcome(0, { break_even: { applies: false, extra_orders: null, ctor_now: null, ctor_needed: null, reason: "some_new_code" } }))).not.toMatch(/some_new_code/);
  });

  it("refusal codes, with or without a suffix, read in Vietnamese; a server message wins", () => {
    expect(refusalText({ refusal: { code: "sku_no_orders:G600013" } })).toMatch(/chưa có đơn trong kỳ/);
    expect(refusalText({ refusal: { code: "voucher_scope_no_data", message: "voucher_scope_no_data" } })).toMatch(/loại voucher này/);
    expect(refusalText({ refusal: "no_campaign_report" })).toMatch(/báo cáo của chiến dịch/);
    expect(refusalText({ refusal: { code: "sku_unknown:G1", message: "Câu riêng của server." } })).toBe("Câu riêng của server.");
    expect(refusalText({ refusal: { code: "brand_new_code" } })).not.toMatch(/brand_new_code/);
  });
});

describe("P96 · numbers only when there is an estimate (J2)", () => {
  it("no per-day / per-order / period lines when the basis is 'không đủ dữ liệu' or profit is unknown", () => {
    const zero = { p50: 0, low: 0, high: 0 };
    const empty = outcome(0, { basis: { key: "insufficient", label: "không đủ dữ liệu" }, delta: { gmv: null, orders: null, profit: null, per_day: { gmv: null, orders: null, profit: zero, cost: 0 }, period: { days: 30, gmv: null, orders: null, profit: zero, cost: 0 } } });
    expect(unitLines(empty)).toEqual([]);
    expect(unitLines(outcome(0)).length).toBeGreaterThanOrEqual(0);
  });
});

describe("P96 · variations (A4, C2, J4)", () => {
  const row = (id: string, stock: number | null, orders?: number): VariationRow => ({ ...variationList().variations[0]!, variation_id: id, stock, ...(orders !== undefined ? { orders_30d: orders } : {}) });

  it("step 2 starts on a variation that sells: orders first, then stock, then the first", () => {
    expect(defaultVariationId([row("old", 0, 0), row("live", 5, 0), row("best", 3, 12)])).toBe("best");
    expect(defaultVariationId([row("old", 0), row("live", 5)])).toBe("live");
    expect(defaultVariationId([row("a", 0), row("b", 0)])).toBe("a");
    expect(defaultVariationId([])).toBeUndefined();
  });

  it("an empty variation id is omitted from add-on rows and price rows", () => {
    const addon = { itemId: "p2", variationId: "", mode: "pct" as const, value: "15", limit: "1" };
    const v = buildVersion("add_on", { ...f, add_on: { addons: [addon] } }, ctx).version as unknown as { addons: Record<string, unknown>[] };
    expect(v.addons[0]).not.toHaveProperty("variation_id");
  });

  it("'Đưa lại listing' is refused for a listing that is selling", () => {
    expect(problem("price_display", { ...f, price_display: { ...f.price_display, what: "listing_relist" } })).toMatch(/đã ẩn hoặc hết hàng/);
    const soldOut = { ...ctx, product: { ...product, stock: 0 } };
    expect(buildVersion("price_display", { ...f, price_display: { ...f.price_display, what: "listing_relist" } }, soldOut).version).toMatchObject({ kind: "listing_relist" });
  });
});
