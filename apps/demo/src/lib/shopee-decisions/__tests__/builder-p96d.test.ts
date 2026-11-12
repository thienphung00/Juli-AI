import { describe, expect, it } from "vitest";

import { baseText, bestBadge, breakEvenText, versionFacts } from "../builder-p92";
import { outcome } from "./builder-fixtures";

/** P96d (owner report 2026-11-06): the compare table tells versions apart — type, inputs, base, break-even. */

const names = { products: { p1: "Túi Bio", p2: "Viên giặt" }, variations: { v1: "18 x 28 cm (220g)" } };

describe("P96d · each version names its type and inputs", () => {
  it("voucher: the four types, amount or %, minimum, limits and the product", () => {
    const shop = versionFacts({ kind: "voucher", scope: "shop", discount_type: "amount", value: 5000, min_spend: 99000, usage_limit: 10 }, names);
    expect(shop.type).toBe("Voucher shop");
    expect(shop.facts.map((f) => [f.label, f.value])).toEqual([
      ["Giảm", "5.000đ"],
      ["Đơn tối thiểu", "99.000đ"],
      ["Lượt dùng tối đa", "10"],
    ]);
    expect(versionFacts({ kind: "voucher", scope: "product", item_ids: ["p1"], discount_type: "pct", value: 10, min_spend: 0, max_value: 20000 }, names)).toMatchObject({
      type: "Voucher sản phẩm",
      facts: expect.arrayContaining([
        { key: "value", label: "Giảm", value: "10%" },
        { key: "max", label: "Giảm tối đa", value: "20.000đ" },
        { key: "product", label: "Sản phẩm", value: "Túi Bio" },
      ]),
    });
    expect(versionFacts({ kind: "voucher", scope: "follower", discount_type: "amount", value: 5000, min_spend: 0 }, names).type).toBe("Voucher người theo dõi / khách mới");
    expect(versionFacts({ kind: "voucher", scope: "livestream", discount_type: "amount", value: 5000, min_spend: 0 }, names).type).toBe("Voucher livestream / video");
  });

  it("other kinds: ads lever and campaign, affiliate commission, flash slots, gift, combo, listing", () => {
    expect(versionFacts({ kind: "ads", lever: "budget", campaign_key: "c1", daily_budget: 186090 }, { ...names, campaigns: { c1: "GMV tối đa — Túi Bio" } })).toMatchObject({
      type: "Quảng cáo · Ngân sách mỗi ngày",
      facts: [
        { key: "campaign", label: "Chiến dịch", value: "GMV tối đa — Túi Bio" },
        { key: "budget", label: "Ngân sách mới mỗi ngày", value: "186.090đ" },
      ],
    });
    expect(versionFacts({ kind: "ads", lever: "roas", campaign_key: "c1", roas_target: 5.3 }, names).facts).toContainEqual({ key: "roas", label: "ROAS mục tiêu mới", value: "5,3" });
    expect(versionFacts({ kind: "affiliate", item_id: "p1", commission_pct: 15, sample_qty: 5, target_campaign: true }, names).facts).toEqual(
      expect.arrayContaining([
        { key: "commission", label: "Hoa hồng mới", value: "15%" },
        { key: "samples", label: "Số mẫu gửi", value: "5" },
      ]),
    );
    expect(versionFacts({ kind: "flash_sale", item_id: "p1", variations: [{ variation_id: "v1", discount_pct: 20 }], units: 50, slot_hours: 2 }, names)).toMatchObject({
      type: "Flash sale",
      facts: expect.arrayContaining([
        { key: "v:v1", label: "Giảm · 18 x 28 cm (220g)", value: "20%" },
        { key: "units", label: "Số lượng (suất)", value: "50" },
        { key: "hours", label: "Số giờ của khung", value: "2" },
      ]),
    });
    expect(versionFacts({ kind: "gift", gift: { unit_cost: 10000, qty: 1, label: "Túi vải" }, trigger: { type: "min_spend", amount: 150000 } }, names)).toMatchObject({
      type: "Deal Sốc · Mua Để Nhận Quà",
      facts: expect.arrayContaining([{ key: "gift", label: "Quà", value: "Túi vải × 1" }, { key: "trigger", label: "Điều kiện nhận quà", value: "Mua 150.000đ để nhận 1 quà tặng" }]),
    });
    // a combo saved as a fixed basket (before P97) stays readable and is named as such
    const legacy = versionFacts({ kind: "combo", items: [{ item_id: "p1", qty: 1 }, { item_id: "p2", qty: 2 }], pricing: "pct", value: 10 }, names);
    expect(legacy.type).toBe("Combo kiểu cũ (giỏ cố định)");
    expect(legacy.facts).toEqual(
      expect.arrayContaining([
        { key: "items", label: "Sản phẩm", value: "Túi Bio × 1 + Viên giặt × 2" },
        { key: "value", label: "% giảm trên tổng", value: "10%" },
      ]),
    );
    expect(versionFacts({ kind: "combo", name: "Mua 2 giảm 5", item_ids: ["p1", "p2"], discount_type: "pct", tiers: [{ qty: 2, value: 5 }, { qty: 3, value: 8 }], purchase_limit: 3 }, names)).toMatchObject({
      type: "Combo khuyến mãi",
      facts: expect.arrayContaining([
        { key: "name", label: "Tên combo", value: "Mua 2 giảm 5" },
        { key: "tier:2", label: "Mua 2 sản phẩm", value: "giảm 5%" },
        { key: "tier:3", label: "Mua 3 sản phẩm", value: "giảm 8%" },
        { key: "limit", label: "Giới hạn đặt hàng", value: "3" },
      ]),
    });
    expect(versionFacts({ kind: "price", item_id: "p1", variations: [{ variation_id: "v1", change_pct: -5 }] }, names).facts).toContainEqual({ key: "v:v1", label: "Thay đổi · 18 x 28 cm (220g)", value: "−5%" });
    expect(versionFacts({ kind: "listing_hide", item_id: "p1" }, names).type).toBe("Ẩn listing");
  });
});

describe("P96d · break-even, base and the badge", () => {
  it("a voucher's AOV break-even reads as the AOV needed, not 'chưa đủ dữ liệu'", () => {
    const o = outcome(0, { break_even: { applies: true, basis: "aov", extra_orders: null, aov_now: 160152, aov_needed: 169761, ctor_now: null, ctor_needed: null } });
    expect(breakEvenText(o)).toBe("cần AOV đơn dùng voucher ≥ 169.761đ (hôm nay 160.152đ), để lợi nhuận không giảm.");
    const none = outcome(0, { break_even: { applies: true, basis: "aov", extra_orders: null, aov_now: null, aov_needed: null, ctor_now: null, ctor_needed: null, reason: "no_qualifying_orders", reason_text: "Chưa có đơn nào đạt đơn tối thiểu." } });
    expect(breakEvenText(none)).toBe("Chưa có đơn nào đạt đơn tối thiểu.");
  });

  it("each column says which orders its 'hôm nay' stands on", () => {
    expect(baseText(outcome(0, { base: { scope: "shop", items: [], aov: 160152, margin_pct: 41.7 } }), names)).toBe("Cả shop · AOV 160.152đ · biên 41,7%");
    expect(baseText(outcome(0, { base: { scope: "product", items: ["p1"], aov: 124580, margin_pct: 33.9 } }), names)).toBe("Túi Bio · AOV 124.580đ · biên 33,9%");
  });

  it("the badge says 'lỗ ít nhất' when the best version still loses money", () => {
    expect(bestBadge(outcome(0, { delta: { ...outcome(0).delta!, profit: { low: -18283, p50: -11959, high: -5634 } } }))).toBe("lỗ ít nhất");
    expect(bestBadge(outcome(0))).toBe("lợi nhuận tốt nhất");
  });
});
