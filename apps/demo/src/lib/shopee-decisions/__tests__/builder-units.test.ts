import { describe, expect, it } from "vitest";

import type { BuilderOutcome } from "../builder-api";
import { unitLines, voucherMaxText, voucherUsageText } from "../builder-p92";

const band = (low: number, p50: number, high: number) => ({ low, p50, high });

function outcome(over: Partial<BuilderOutcome> = {}): BuilderOutcome {
  return {
    index: 0,
    kind: "voucher",
    label: "P1",
    ok: true,
    delta: {
      gmv: band(0, 90_000, 200_000),
      orders: band(0, 0, 0),
      profit: band(-30_000, 6000, 40_000),
      days: 3,
      per_day: { gmv: band(0, 30_000, 66_000), orders: band(0, 0, 0), profit: band(-10_000, 2000, 13_300), cost: 10_000 },
      period: { days: 3, gmv: band(0, 90_000, 200_000), orders: band(0, 0, 0), profit: band(-30_000, 6000, 40_000), cost: 30_000 },
      per_order: { basis: "voucher_use", orders: 6, cost: 5000, profit: band(-5000, 1000, 6600) },
    },
    voucher: {
      days: 3,
      usage: { expected_uses: 6, used: 6, limit: 20, capped: false, headroom: 14 },
      per_user: { limit: 1, status: "not_enforceable", enforced: false },
      max_discount: { value: 20_000, applies: true, pct_voucher: true, binding_orders: 2, qualifying_orders: 10, binding_share: 0.2 },
      min_spend: { value: 99_000, qualifying_orders: 10, total_orders: 40 },
      cost_per_used_order: 5000,
      profit_per_order_after: 30_000,
    },
    ...over,
  } as BuilderOutcome;
}

describe("builder outcome units", () => {
  it("says per day, per order using the voucher and over the voucher's own days", () => {
    expect(unitLines(outcome())).toEqual([
      "Mỗi ngày: +2.000đ lợi nhuận (−10.000đ – +13.300đ)",
      "Mỗi đơn dùng voucher: +1.000đ lợi nhuận, chi phí 5.000đ",
      "Trong 3 ngày: +6.000đ (−30.000đ – +40.000đ)",
    ]);
  });

  it("names expected usage against the limit and whether the max discount binds", () => {
    expect(voucherUsageText(outcome())).toBe("Dự kiến dùng 6 / 20 lượt · chưa chạm giới hạn");
    const capped = outcome({ voucher: { ...outcome().voucher!, usage: { expected_uses: 9, used: 5, limit: 5, capped: true, headroom: 0 } } });
    expect(voucherUsageText(capped)).toBe("Dự kiến dùng 5 / 5 lượt · chạm giới hạn");
    expect(voucherMaxText(outcome())).toBe("Mức giảm tối đa chạm ở 2/10 đơn đủ điều kiện");
    expect(voucherUsageText(outcome({ voucher: null }))).toBeNull();
  });
});
