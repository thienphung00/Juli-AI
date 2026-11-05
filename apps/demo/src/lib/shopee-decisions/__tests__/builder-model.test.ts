import { describe, expect, it } from "vitest";

import { PCT_ONLY, compareBody, compareRows, defaultDiscount, discountLabel, floorAlerts, floorLines, orderLines, presetOf, sendable, toVariant, tradeoffs, type BuilderVariant } from "../builder-model";
import { compareResult, voucherCard } from "./fixtures";

const products = [
  { id: "GT-A", name: "Găng tay cao su A" },
  { id: "TR-B", name: "Túi rác sinh học B" },
  { id: "MR-C", name: "Miếng rửa chén C" },
];

describe("presets of a change type", () => {
  it("combo: two of the focus product and one of the next, 10%", () => {
    const v = presetOf("combo", products, "TR-B");
    expect(v.items.map((i) => [i.id, i.qty])).toEqual([["TR-B", 2], ["GT-A", 1], ["", 0]]);
    expect([v.dtype, v.dval, v.voucher, v.gift]).toEqual(["pct", 10, null, null]);
  });
  it("mua kèm is an amount, quà tặng gifts the second product, voucher and giảm giá take %", () => {
    expect(presetOf("addon", products, null)).toMatchObject({ dtype: "amt", dval: 10000 });
    expect(presetOf("gift", products, null)).toMatchObject({ dtype: "pct", dval: 5, gift: "TR-B" });
    expect(presetOf("voucher", products, null).voucher).toEqual({ v: 15000, min: 150000 });
    expect(presetOf("disc", products, null)).toMatchObject({ dtype: "pct", dval: 8 });
    expect(PCT_ONLY.has("disc")).toBe(true);
  });
  it("formats the discount and a default when the type changes", () => {
    expect(discountLabel("pct", 10)).toBe("10%");
    expect(discountLabel("amt", 20000)).toBe("20.000đ");
    expect(defaultDiscount("pct", null)).toBe(10);
    expect(defaultDiscount("amt", null)).toBe(20000);
    expect(defaultDiscount("price", 237000)).toBe(199000);
  });
});

describe("a variant as the backend takes it", () => {
  it("combo -> combo_multi with combo_items, discount_type amount|pct|fixed_price, voucher and gift", () => {
    const v: BuilderVariant = { ...presetOf("combo", products, "GT-A"), dtype: "price", dval: 199000, voucher: { v: 10000, min: 200000 }, gift: "MR-C" };
    expect(toVariant(v, "P1").input).toEqual({
      label: "P1",
      change_kind: "combo_multi",
      items: ["GT-A", "TR-B"],
      extra: { combo_items: [{ item_id: "GT-A", qty: 2 }, { item_id: "TR-B", qty: 1 }], discount_type: "fixed_price", discount_value: 199000, voucher: { value: 10000, min_spend: 200000 }, gift_item: "MR-C" },
      inputs: {},
    });
    expect(toVariant({ ...v, dtype: "amt", voucher: null, gift: null }).input?.extra.discount_type).toBe("amount");
  });
  it("one product is not a combo", () => {
    const v = { ...presetOf("combo", products, "GT-A"), items: [{ id: "GT-A", qty: 2 }, { id: "", qty: 0 }, { id: "", qty: 0 }] };
    expect(toVariant(v)).toEqual({ input: null, problem: "Combo cần 2 hoặc 3 sản phẩm." });
  });
  it("voucher -> min_spend_voucher; giảm giá -> product_discount; ads and title are not compared here", () => {
    expect(toVariant(presetOf("voucher", products, "GT-A")).input).toMatchObject({ change_kind: "min_spend_voucher", items: ["GT-A"], inputs: { value: 15000, max_value: 15000, min_spend: 150000 } });
    expect(toVariant(presetOf("disc", products, "GT-A")).input).toMatchObject({ change_kind: "product_discount", items: ["GT-A"], inputs: { discount_pct: 8 } });
    expect(toVariant(presetOf("ads", products, "GT-A"))).toEqual({ input: null, problem: null });
    expect(toVariant(presetOf("title", products, "GT-A"))).toEqual({ input: null, problem: null });
  });
  it("compare takes 2-4: a single variant is sent twice and read once", () => {
    const one = sendable([presetOf("combo", products, "GT-A")]);
    expect(compareBody(one)).toHaveLength(2);
    const two = sendable([presetOf("combo", products, "GT-A"), presetOf("ads", products, null), presetOf("addon", products, "GT-A")]);
    expect(two.map((s) => s.index)).toEqual([0, 2]);
    expect(compareBody(two)).toHaveLength(2);
  });
});

describe("reading the comparison", () => {
  const vars = [presetOf("combo", products, "GT-A"), presetOf("addon", products, "GT-A"), presetOf("combo", products, "GT-A")];
  const sent = sendable(vars);
  const result = compareResult(3);

  it("rows: today, per-variant value with Δ vs hôm nay and vs the first, the floor row", () => {
    const rows = compareRows(result, sent, 3);
    expect(rows.map((r) => r.label)).toEqual(["Lợi nhuận", "Biên", "AOV", "Số đơn", "GMV", "Chi phí", "Giá sàn"]);
    const profit = rows[0]!;
    expect(profit.cells[0]).toMatchObject({ v: "−60.000đ – +220.000đ", d: "▲ +60.000đ", vs: "phương án gốc" });
    expect(profit.cells[1]!.vs).toBe("so P1: +20.000đ");
    const bien = rows[1]!;
    expect(bien.today).toBe("15,3%");
    expect(bien.cells[0]!.v).toBe("14,9%");
    expect(bien.cells[0]!.d).toBe("▼ −0,4 điểm");
    expect(bien.cells[0]!.tone).toBe("down");
    expect(rows[2]!.today).toBe("165.000đ");
    expect(rows[3]!.cells[0]!.v).toBe("126");
    expect(rows[5]!.cells[0]!.tone).toBe("down");
    const floor = rows[6]!;
    expect(floor.cells[0]!.v).toBe("✓ Trên giá sàn vận hành");
    expect(floor.cells[2]!.v).toBe("✕ BEP-S5-CB");
  });

  it("a variant of a kind that is compared in its card has no cell", () => {
    const withAds = [vars[0]!, presetOf("ads", products, null)];
    const s = sendable(withAds);
    const rows = compareRows(compareResult(2), s, 2);
    expect(rows[0]!.cells[1]).toBeNull();
  });

  it("names the trade-off when margin falls and the basket grows, and each variant that breaks a floor", () => {
    const base = compareResult(3);
    const between = [
      { from: 0, to: 1, delta: { margin_points_p25: -1.2, aov_p25: 15000, dgmv_p50: 300000, dprofit_p50: 30000 } },
      { from: 0, to: 2, delta: { margin_points_p25: 0.2, aov_p25: 15000, dgmv_p50: 0, dprofit_p50: 0 } },
    ];
    const t = tradeoffs({ ...base, between }, sent);
    expect(t).toEqual(["P2 so với P1: biên giảm 1,2 điểm nhưng AOV tăng 15.000đ, GMV +300.000đ, lợi nhuận +30.000đ trong kỳ tính. Chọn theo việc bạn cần: lợi nhuận hay doanh thu."]);
    const alerts = floorAlerts(base, sent, (id) => id);
    expect(alerts).toHaveLength(1);
    expect(alerts[0]!.title).toBe("P3 chạm giá sàn.");
    expect(alerts[0]!.text).toContain("175.000đ < sàn vận hành 181.979đ");
    expect(alerts[0]!.text).toContain("Vẫn lưu được sau khi bạn xác nhận cảnh báo.");
  });

  it("one order of a combo, from the calculator's own arithmetic; nothing for the other kinds", () => {
    const combo = voucherCard({ certain: { label: "Chắc chắn", combo_multi: true, list_value: 237000, combo_discount: 23700, voucher_discount: 0, buyer_pays: 213300, cogs: 100000, packaging: 8000, gift_cost: null, platform_fees: 38000, contribution: 40000, contribution_without_offer: 52000, margin_pct: 18.8, cost_per_combo_order: 12000, break_even_extra_orders: 4 } });
    const row = { ...result.variants[0]!, card: combo };
    const lines = orderLines(row, 15.3)!;
    expect(Object.fromEntries(lines.map((l) => [l.k, l.v]))).toMatchObject({
      "Giá niêm yết cả giỏ": "237.000đ",
      "Giảm giá": "−23.700đ",
      "Voucher cộng thêm": "—",
      "Khách trả": "213.300đ",
      "Giá vốn + đóng gói": "−108.000đ",
      "Phí sàn (một lần cho đơn)": "−38.000đ",
      "Đóng góp mỗi đơn": "40.000đ",
      "Biên của đơn combo": "18,8% (hôm nay 15,3%)",
      "Chi phí ưu đãi mỗi đơn": "12.000đ",
      "Hoà vốn": "Cần ≥ 4 đơn combo thêm trong kỳ tính",
    });
    expect(lines.find((l) => l.k === "Đóng góp mỗi đơn")!.tone).toBe("down");
    expect(orderLines(result.variants[0], null)).toBeNull();
    expect(floorLines({ ...row, card: { ...combo, certain: { ...combo.certain, lines: [{ item_id: "GT-A", unit_paid: 90000, floor: 95000, below_floor: true }] } } }, () => "Găng tay cao su A")).toEqual([
      { name: "Găng tay cao su A", bad: true, text: "✕ 90.000đ / sản phẩm, sàn vận hành 95.000đ" },
    ]);
  });
});
