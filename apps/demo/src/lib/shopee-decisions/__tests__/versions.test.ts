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
    expect(exp.cells[0]!.v).toBe("−43.000đ – +237.000đ/tháng");
    expect(rows.find((r) => r.key === "sure")!.cells[0]!.v).toBe("−63.000đ/tháng");
    expect(rows.find((r) => r.key === "cap")!.cells[0]!.v).toBe("✓ 1.112.311đ / 1.200.000đ mỗi ngày");
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
