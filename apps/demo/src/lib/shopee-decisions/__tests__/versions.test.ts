import { describe, expect, it } from "vitest";

import { ackText, breachNoun, breachVerb, breachWarnLines, breachesOf, cardOfVersion, measuringDaysLeft, queueLabel, rangeK, rangeTone, svk, titleCount, versionCode, versionFlag, versionTable, versionTag, versionsOf, vnWhenFull } from "../versions";
import { ABSOLUTE_BREACH, OPERATING_BREACH, titleCard, versionOf, versionedVoucher, voucherCard } from "./fixtures";

describe("money to the nearest nghìn", () => {
  it("prints signed and ranged values like the artboards", () => {
    expect(svk(60_400)).toBe("+60.000đ");
    expect(svk(-1_000)).toBe("−1.000đ");
    expect(svk(null)).toBe("—");
    expect(rangeK(210_000, 60_000)).toBe("+60.000đ – +210.000đ");
    expect(rangeK(60_100, 59_900)).toBe("+60.000đ");
    expect(rangeTone(10, 100)).toBe("up");
    expect(rangeTone(-100, -10)).toBe("down");
    expect(rangeTone(-10, 100)).toBe("plain");
  });
});

describe("queue and measuring", () => {
  it("labels the place in the product's queue", () => {
    expect(queueLabel(1)).toBe("#1 · Đang ở Quyết định");
    expect(queueLabel(4)).toBe("#4 · Xếp hàng");
    expect(queueLabel(null)).toBe("—");
  });

  it("counts the days left of the window, both ends included, in Vietnam time", () => {
    const now = new Date("2026-11-12T01:00:00Z");
    expect(measuringDaysLeft({ until: "2026-11-14" }, now)).toBe(3);
    expect(measuringDaysLeft({ until: "2026-11-12" }, now)).toBe(1);
    expect(measuringDaysLeft({ until: "2026-11-11" }, now)).toBe(0);
    expect(measuringDaysLeft(null, now)).toBe(0);
  });
});

describe("breaches never block, they are named", () => {
  it("reads floor and spend-cap breaches off one evaluation", () => {
    const card = voucherCard({ floor: { breaches: [OPERATING_BREACH], unknown_skus: [], ok: false }, spend: { shop_chi_per_day_now: 1, card_dchi_per_day: 1, shop_chi_per_day_after: 1_220_000, cap: 1_200_000, over_cap: true } });
    const bs = breachesOf(card);
    expect(bs.map((b) => b.type)).toEqual(["floor", "spend_cap"]);
    expect(breachNoun(bs)).toBe("chạm giá sàn và vượt trần chi");
    expect(breachVerb(bs)).toBe("vượt giá sàn và trần chi");
    expect(breachWarnLines(bs)).toEqual([
      "Giá sàn: BEP-S5-CB, khách trả 175.000đ thấp hơn sàn vận hành 181.979đ, thiếu 6.979đ (chưa lỗ).",
      "Trần chi: chi marketing 1.220.000đ / ngày vượt trần 1.200.000đ, vượt 20.000đ mỗi ngày.",
    ]);
  });

  it("says 'đang lỗ' under the absolute floor", () => {
    expect(breachWarnLines([{ type: "floor", ...ABSOLUTE_BREACH }])[0]).toContain("giá sàn tuyệt đối 121.176đ, thiếu 11.176đ (đang lỗ)");
  });

  it("the acknowledgement chip carries the time in Vietnam time", () => {
    expect(vnWhenFull("2026-11-04T03:15:00")).toBe("04/11/2026 10:15");
    expect(ackText([{ type: "floor" }], "2026-11-04T03:15:00")).toBe("Đã xác nhận vượt giá sàn · 04/11/2026 10:15");
    expect(ackText([{ type: "spend_cap" }], "2026-11-04T03:15:00")).toBe("Đã xác nhận vượt trần chi · 04/11/2026 10:15");
  });
});

describe("title limit (D-4)", () => {
  it("counts to 100 and says what is over", () => {
    expect(titleCount("a".repeat(97))).toMatchObject({ n: 97, over: false, tone: "warn", note: "Còn 3 ký tự." });
    expect(titleCount("a".repeat(100)).over).toBe(false);
    expect(titleCount("a".repeat(104))).toMatchObject({ over: true, tone: "down", note: "Quá 4 ký tự. Phần vượt không được lưu và Duyệt bị khoá." });
    expect(titleCount("a".repeat(50)).tone).toBe("up");
  });
});

describe("versions of a card", () => {
  it("a card from before P91 is one version", () => {
    const vs = versionsOf(voucherCard({ code: "JC-2611-0001" }));
    expect(vs).toHaveLength(1);
    expect(vs[0]).toMatchObject({ version: 1, code: "JC-2611-0001-V1", ranked: true, status: "ok" });
  });

  it("puts a version's evaluation over the card", () => {
    const card = versionedVoucher();
    const v2 = card.versions![1]!;
    const shown = cardOfVersion(card, v2);
    expect(shown.inputs).toEqual(v2.inputs);
    expect(shown.five_numbers).toBe(v2.five_numbers);
    expect(shown.title).toBe(card.title);
  });

  it("a refused version leaves the card as it is", () => {
    const card = versionedVoucher();
    const refused = { ...versionOf(card, 4, "Không tính được"), status: "refused", refusal: "cost_or_fee_unknown", five_numbers: undefined };
    expect(cardOfVersion(card, refused)).toBe(card);
    expect(versionTag(refused, 3)).toEqual({ text: "Không tính được", tone: "down" });
  });

  it("tags the engine's pick and the breaching ones; codes fall back to <card>-Vn", () => {
    const card = versionedVoucher();
    expect(versionTag(card.versions![0]!, 0)).toEqual({ text: "Juli đề xuất", tone: "pink" });
    expect(versionTag(card.versions![1]!, 1)).toEqual({ text: "Phiên bản", tone: "flat" });
    expect(versionTag(card.versions![2]!, 2)).toEqual({ text: "Chạm giá sàn", tone: "down" });
    expect(versionCode({ code: "JC-2611-0007" }, { version: 2, code: null })).toBe("JC-2611-0007-V2");
    expect(versionFlag({ status: "floor_breach" })).toBe("Chạm giá sàn");
    expect(versionFlag({ status: "ok" })).toBe("");
  });
});

describe("the side-by-side table", () => {
  it("has the artboard's rows, one cell per version, and flags the breaching column", () => {
    const card = versionedVoucher();
    const rows = versionTable(card, card.versions!);
    expect(rows.map((r) => r.label)).toEqual(["① Giảm giá", "② Hiệu quả chi", "③ Biên lợi nhuận", "④ Số đơn", "⑤ AOV", "Chi phí", "Δ lợi nhuận · chắc chắn", "Δ lợi nhuận · dự kiến", "Giá sàn", "Trần chi"]);
    expect(rows.every((r) => r.cells.length === 3)).toBe(true);
    const floor = rows.find((r) => r.key === "floor")!;
    expect(floor.cells[0]!.v).toBe("✓ Trên giá sàn vận hành");
    expect(floor.cells[2]).toMatchObject({ bad: true, tone: "down" });
    expect(floor.cells[2]!.v).toContain("✕ Khách trả 175.000đ < sàn 181.979đ (thiếu 6.979đ)");
    const exp = rows.find((r) => r.key === "exp")!;
    expect(exp.cells[0]!.v).toBe("−1.400đ – +7.900đ/ngày");
    expect(exp.cells[0]!.d).toContain("30 ngày: −43.000đ – +237.000đ");
    expect(rows.find((r) => r.key === "sure")!.cells[0]!.v).toBe("−2.100đ/ngày");
    expect(rows.find((r) => r.key === "cap")!.cells[0]!.v).toBe("✓ Chi marketing dự kiến 1.112.311đ/ngày · trong trần 1.200.000đ/ngày");
  });

  it("a voucher shows usage against its limit, the per-buyer limit, the max discount and why versions match; flows are per day and per order", () => {
    const base = versionedVoucher();
    const detail = (used: number, limit: number | null, capped: boolean, binding = 0) => ({
      days: 3,
      usage: { expected_uses: used, used, limit, capped, headroom: limit === null ? null : Math.max(limit - used, 0) },
      per_user: { limit: 1, status: "not_enforceable", enforced: false },
      max_discount: { value: 20_000, applies: true, pct_voucher: true, binding_orders: binding, qualifying_orders: 10, binding_share: binding / 10 },
      min_spend: { value: 99_000, qualifying_orders: 10, total_orders: 40 },
      cost_per_used_order: 5000,
      profit_per_order_after: 30_000,
    });
    const money = {
      ...base.predicted.money_per_month,
      days: 3,
      period: { days: 3, certain: { dgmv: 0, dprofit: -30_000, dchi: 30_000 }, total: { p10: { dgmv: 0, dorders: null, dprofit: -30_000 }, p50: { dgmv: 90_000, dorders: null, dprofit: 6000 }, p90: { dgmv: 200_000, dorders: null, dprofit: 40_000 } } },
      per_day: { certain: { dgmv: 0, dprofit: -10_000, dchi: 10_000 }, total: { p10: { dgmv: 0, dorders: null, dprofit: -10_000 }, p50: { dgmv: 30_000, dorders: null, dprofit: 2000 }, p90: { dgmv: 66_000, dorders: null, dprofit: 13_300 } } },
      per_order: { basis: "voucher_use" as const, orders_in_period: 6, certain: { dprofit: -5000, cost: 5000 }, total: { p10: { dprofit: -5000 }, p50: { dprofit: 1000 }, p90: { dprofit: 6600 } } },
      orders: { base_per_day: 2, total: { p10: { per_day: 2, period: 6, changes: false }, p50: { per_day: 2, period: 6, changes: false }, p90: { per_day: 2, period: 6, changes: false } } },
      aov: { base: 100_000, certain: 100_000, total: { p10: 103_000, p50: 108_000, p90: 112_000 } },
    };
    const mk = (limit: number, capped: boolean, notes?: readonly string[]) => ({
      ...base.versions![0]!,
      certain: { ...base.certain, voucher_detail: detail(6, limit, capped) },
      predicted: { ...base.predicted, money_per_month: money },
      same_as_default_notes: notes,
    });
    const versions = [mk(10, false), mk(20, false, ["Giới hạn 20 lượt không đổi kết quả: dự kiến chỉ dùng 6 lượt trong 3 ngày, chưa chạm giới hạn."]), mk(5, true)];
    const card = { ...base, versions, certain: versions[0]!.certain, predicted: versions[0]!.predicted };
    const rows = versionTable(card, versions);
    const by = (k: string) => rows.find((r) => r.key === k)!;
    expect(by("usage").cells.map((c) => c.v)).toEqual(["Dự kiến dùng 6 / 10 lượt", "Dự kiến dùng 6 / 20 lượt", "Dự kiến dùng 6 / 5 lượt"]);
    expect(by("usage").cells.map((c) => c.d)).toEqual(["chưa chạm giới hạn", "chưa chạm giới hạn", "chạm giới hạn"]);
    expect(by("same").cells[1]!.v).toContain("Giới hạn 20 lượt không đổi kết quả");
    expect(by("peruser").cells[0]!.v).toBe("1 lượt/người");
    expect(by("maxd").cells[0]!.d).toBe("chưa đơn nào chạm trần");
    // units: per day, per order, the whole period; never per month
    expect(by("chi").cells[0]).toMatchObject({ v: "+10.000đ/ngày" });
    expect(by("chi").cells[0]!.d).toBe("5.000đ/đơn dùng voucher · 3 ngày: +30.000đ");
    expect(by("sure").cells[0]!.v).toBe("−10.000đ/ngày");
    expect(by("sure").cells[0]!.d).toBe("−5.000đ/đơn dùng voucher · 3 ngày: −30.000đ");
    expect(by("exp").cells[0]!.d).toContain("3 ngày: −30.000đ – +40.000đ");
    expect(by("orders").cells[0]!.v).toBe("2,0 đơn/ngày");
    expect(by("orders").cells[0]!.d).toContain("số đơn giữ nguyên");
    expect(by("aov").cells[0]).toMatchObject({ v: "103.000đ – 112.000đ", d: "AOV giữ nguyên ở lớp chắc chắn" });
    expect(rows.some((r) => r.label.includes("tháng") || r.sub.includes("tháng"))).toBe(false);
  });

  it("a title card swaps the floor and the cap for the 100-character limit", () => {
    const card = titleCard();
    const rows = versionTable(card, card.versions!);
    expect(rows.find((r) => r.key === "cap")).toBeUndefined();
    expect(rows.find((r) => r.key === "floor")!.cells[0]!.v).toBe("Không áp dụng: không đổi giá");
    const limit = rows.find((r) => r.key === "limit")!;
    expect(limit.label).toBe("Giới hạn 100 ký tự");
    expect(limit.cells[0]!.v).toMatch(/^✓ \d+\/100 ký tự · không tốn chi phí$/);
    expect(rows.find((r) => r.key === "sure")!.cells[0]!.v).toBe("Không tốn chi phí");
  });
});
