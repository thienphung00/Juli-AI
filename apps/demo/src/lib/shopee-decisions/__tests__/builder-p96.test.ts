import { describe, expect, it } from "vitest";

import { createBuilderApi, type VariationRow } from "../builder-api";
import { breakEvenText, buildVersion, defaultVariationId, initialForms, refusalText, unitLines, type Forms } from "../builder-p92";
import { outcome, pickerProducts, variationList } from "./builder-fixtures";

/** P96 (2026-11-05 ORY sweep): the builder refuses in Vietnamese what the server would 422, never prints codes. */

const product = pickerProducts().products[0]!;
const ctx = { product, variations: variationList().variations.slice(0, 2) };
const f = initialForms();
const problem = (kind: Parameters<typeof buildVersion>[0], forms: Forms, c = ctx) => buildVersion(kind, forms, c).problem;
/** The Deal Sốc form (P100 wave 2) with `patch` on top of its defaults, as the type `add_on`. */
const deal = (patch: Partial<Forms["deal_soc"]>): Forms => ({ ...f, deal_soc: { ...f.deal_soc, ...patch } });
/** The same, as Mua Để Nhận Quà with `gift` on top of its defaults. */
const giftDeal = (gift: Partial<Forms["deal_soc"]["gift"]>, patch: Partial<Forms["deal_soc"]> = {}): Forms => deal({ type: "gift", gift: { ...f.deal_soc.gift, ...gift }, ...patch });

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
    expect(problem("deal_soc", deal({ addons: [addon] }))).toMatch(/tối đa 90%/);
    expect(problem("product_discount", { ...f, product_discount: { ...f.product_discount, rows: [{ variationId: "v3", value: "95" }] } })).toMatch(/tối đa 90%/);
    expect(problem("price_flash", { ...f, price_flash: { ...f.price_flash, what: "flash_sale", rows: [{ variationId: "v3", value: "95" }] } })).toMatch(/tối đa 90%/);
    expect(problem("combo", { ...f, combo: { ...f.combo, items: ["a", "b"], tiers: [{ qty: "2", value: "95" }] } })).toMatch(/tối đa 90%/);
  });

  it("0 is refused, not clamped to 1: gift qty, add-on limit, pack count, per-buyer of a discount, flash hours", () => {
    expect(problem("deal_soc", giftDeal({ giftItemId: "p2", qty: "0" }))).toMatch(/Số quà tặng/);
    expect(problem("deal_soc", giftDeal({ giftItemId: "p2", qty: "50" }))).toMatch(/dưới 50/);
    expect(buildVersion("deal_soc", giftDeal({ giftItemId: "p2", qty: "49" }), ctx).version).toMatchObject({ kind: "gift", gift: { qty: 49 } });
    const addon = { itemId: "p2", variationId: "", mode: "pct" as const, value: "15", limit: "0" };
    expect(problem("deal_soc", deal({ addons: [addon] }))).toMatch(/Giới hạn mỗi đơn/);
    expect(problem("variation_set", { ...f, variation_set: { rows: [{ name: "Set 3", price: "270000", sku: "", packCount: "0", stock: "" }] } })).toMatch(/Số lượng trong gói/);
    expect(problem("product_discount", { ...f, product_discount: { ...f.product_discount, rows: [{ variationId: "v3", value: "10" }], perBuyer: "0" } })).toMatch(/Giới hạn đặt hàng/);
    expect(problem("price_flash", { ...f, price_flash: { ...f.price_flash, what: "flash_sale", rows: [{ variationId: "v3", value: "10" }], slotHours: "0" } })).toMatch(/Số giờ/);
  });

  it("a gift that is not sold needs a name", () => {
    const g = { source: "unsold" as const, unitCost: "10000", label: "" };
    expect(problem("deal_soc", giftDeal(g))).toBe("Nhập tên quà.");
    expect(buildVersion("deal_soc", giftDeal({ ...g, label: "Túi vải" }), ctx).version).toMatchObject({ gift: { label: "Túi vải" } });
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
    const v = buildVersion("deal_soc", deal({ addons: [addon] }), ctx).version as unknown as { addons: Record<string, unknown>[] };
    expect(v.addons[0]).not.toHaveProperty("variation_id");
  });
});

describe("P100 wave 2 · Deal Sốc, one form with two types (brief C, B.14)", () => {
  const addon = { itemId: "p2", variationId: "", mode: "price" as const, value: "20000", limit: "1" };

  it("Mua Kèm Deal Sốc: name, dates with hours, Giới hạn sản phẩm mua kèm (≤ 100) become the add_on version", () => {
    const form = deal({ name: "Mua kèm tháng 12", start: "2026-12-01", end: "2026-12-10", startHour: "9", endHour: "21", addonLimit: "50", addons: [addon] });
    expect(buildVersion("deal_soc", form, ctx).version).toMatchObject({ kind: "add_on", name: "Mua kèm tháng 12", label: "Mua kèm tháng 12", start: "2026-12-01", end: "2026-12-10", start_hour: 9, end_hour: 21, addon_limit: 50, main_item_id: product.item_id });
    expect(problem("deal_soc", deal({ addons: [addon], addonLimit: "101" }))).toMatch(/Giới hạn sản phẩm mua kèm từ 1 đến 100/);
    expect(problem("deal_soc", deal({ addons: [addon], addonLimit: "0" }))).toMatch(/Giới hạn sản phẩm mua kèm/);
  });

  it("Mua Để Nhận Quà: Mua ₫X để nhận N quà tặng becomes a min_spend gift; the type switch picks the server kind", () => {
    const v = buildVersion("deal_soc", giftDeal({ giftItemId: "p2", minSpend: "200000", qty: "3" }, { name: "Quà tháng 12" }), ctx).version;
    expect(v).toMatchObject({ kind: "gift", name: "Quà tháng 12", trigger: { type: "min_spend", amount: 200000 }, gift: { item_id: "p2", qty: 3 } });
    expect(problem("deal_soc", giftDeal({ giftItemId: "p2", minSpend: "" }))).toMatch(/số tiền mua/);
    expect(buildVersion("deal_soc", deal({ type: "add_on", addons: [addon] }), ctx).version).toMatchObject({ kind: "add_on" });
  });

  it("the window needs an end after the start (≥ 1 hour), hours 0-23 and a date for each hour; the name is ≤ 150 characters", () => {
    expect(problem("deal_soc", deal({ addons: [addon], start: "2026-12-01", end: "2026-12-01", startHour: "10", endHour: "10" }))).toMatch(/tối thiểu 1 giờ/);
    expect(problem("deal_soc", deal({ addons: [addon], start: "2026-12-02", end: "2026-12-01" }))).toMatch(/kết thúc/);
    expect(problem("deal_soc", deal({ addons: [addon], startHour: "24", start: "2026-12-01" }))).toMatch(/0 đến 23/);
    expect(problem("deal_soc", deal({ addons: [addon], startHour: "9" }))).toMatch(/Chọn ngày/);
    expect(problem("deal_soc", deal({ addons: [addon], name: "x".repeat(151) }))).toMatch(/150/);
  });
});

describe("P100 wave 2 · Chương Trình Của Shop (brief C, B.14)", () => {
  const d = { ...f.product_discount, rows: [{ variationId: "v3", value: "10" }] };
  const disc = (patch: Partial<typeof d>): Forms => ({ ...f, product_discount: { ...d, ...patch } });

  it("carries Tên chương trình khuyến mãi, the hours, Số lượng sản phẩm khuyến mãi and Giới hạn đặt hàng", () => {
    const form = disc({ name: "Sale 12.12", start: "2026-12-12", end: "2026-12-14", startHour: "0", endHour: "23", promoQty: "200", perBuyer: "2" });
    expect(buildVersion("product_discount", form, ctx).version).toMatchObject({ kind: "product_discount", name: "Sale 12.12", label: "Sale 12.12", start_hour: 0, end_hour: 23, promo_qty: 200, per_buyer_limit: 2, variations: [{ variation_id: "v3", discount_pct: 10 }] });
    expect(buildVersion("product_discount", disc({}), ctx).version).not.toHaveProperty("promo_qty");
  });

  it("runs at most 180 days, hours counted; promo quantity from 1", () => {
    expect(problem("product_discount", disc({ start: "2026-01-01", end: "2026-07-01" }))).toMatch(/tối đa 180 ngày/);
    expect(problem("product_discount", disc({ start: "2026-01-01", end: "2026-06-29" }))).toBeNull();
    expect(problem("product_discount", disc({ promoQty: "0" }))).toMatch(/Số lượng sản phẩm khuyến mãi/);
    expect(problem("product_discount", disc({ start: "2026-12-01", end: "2026-12-01", startHour: "8", endHour: "8" }))).toMatch(/tối thiểu 1 giờ/);
  });
});
