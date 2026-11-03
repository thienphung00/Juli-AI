import { describe, expect, it } from "vitest";

import { fiveCards, freshnessOf, impactsOf, isStale, weakestLink } from "../model";
import { WINDOW, five, overview } from "./fixtures";

describe("impacts: ₫ per day each link of the chain pulled GMV", () => {
  it("the four links add up to the GMV change per day", () => {
    const ov = overview();
    const i = impactsOf(ov.kpi_strip, WINDOW.days);
    const sum = (i.views ?? 0) + (i.ctr ?? 0) + (i.ctor ?? 0) + (i.aov ?? 0);
    expect(i.gmv).toBeCloseTo((50_000_000 - 46_900_000) / 30, 6);
    // The strip's views × CTR × CTOR × AOV is GMV to within rounding of the printed rates.
    expect(Math.abs(sum - (i.gmv ?? 0)) / (i.gmv ?? 1)).toBeLessThan(0.1);
  });

  it("adds up exactly when the chain is exact", () => {
    const strip = {
      ...overview().kpi_strip,
      gmv: { value: 50_000_000, previous: 40_000_000, change_pct: 25 },
      views: { value: 100_000, previous: 80_000, change_pct: 25 },
      ctr: { value: 0.05, previous: 0.04, change_pct: 25 },
      ctor: { value: 0.1, previous: 0.1, change_pct: 0 },
      aov: { value: 100_000, previous: 125_000, change_pct: -20 },
    };
    const i = impactsOf(strip, 10);
    expect((i.views ?? 0) + (i.ctr ?? 0) + (i.ctor ?? 0) + (i.aov ?? 0)).toBeCloseTo(i.gmv ?? 0, 6);
    expect(i.ctor).toBeCloseTo(0, 6);
    expect(i.aov ?? 0).toBeLessThan(0);
    expect(weakestLink(i)).toBe("aov");
  });

  it("is unknown without a previous period", () => {
    const ov = overview();
    const strip = { ...ov.kpi_strip, gmv: { value: 1, previous: null, change_pct: null } };
    expect(impactsOf(strip, 30).gmv).toBeNull();
    expect(impactsOf(strip, 30).views).toBeNull();
  });

  it("names the weakest link only when one is negative", () => {
    const ov = overview();
    expect(weakestLink(impactsOf(ov.kpi_strip, 30))).toBe("ctr");
    expect(weakestLink({ views: 1, ctr: 2, ctor: 3, aov: 4, gmv: 10 })).toBeNull();
  });
});

describe("five numbers", () => {
  it("prints the contract-5 labels, VND and %", () => {
    const cards = fiveCards(five(), 10);
    expect(cards.map((c) => c.label)).toEqual([
      "① % giảm giá",
      "② Doanh thu thêm / chi thêm",
      "③ Biên lợi nhuận cuối",
      "④ Số đơn",
      "⑤ AOV",
      "Chi marketing / ngày vs trần",
    ]);
    expect(cards[0]!.value).toBe("8,4%");
    expect(cards[0]!.sub1).toBe("= 4.200.000đ tiền giảm");
    expect(cards[1]!.value).toBe("2,50đ / 1đ chi");
    expect(cards[3]!.value).toBe("250 đơn");
    expect(cards[4]!.value).toBe("200.000đ");
    expect(cards[5]!.value).toBe("1.110.211đ/ngày");
    expect(cards[5]!.sub2).toBe("Còn 89.789đ (8%)");
  });

  it("shows 'trên X % doanh thu có giá vốn' and no profit in đồng below 100 % coverage", () => {
    const m = fiveCards(five(), 10)[2]!;
    expect(m.sub1).toBe("trên 99,4% doanh thu có giá vốn");
    expect(m.sub1).not.toContain("lợi nhuận");
  });

  it("shows the profit in đồng at 100 % coverage", () => {
    const f = five({ margin: { profit_before: 1, profit_after: 7_000_000, pct_before: 10, pct_after: 14, is_partial: false, cost_coverage_pct: 100 } });
    expect(fiveCards(f, 10)[2]!.sub1).toBe("= 7.000.000đ lợi nhuận");
  });

  it("says 'giảm chi' instead of a red 0đ / 1đ when spend did not grow", () => {
    const f = five({ extra_revenue_per_extra_spend: { extra_revenue: 100, extra_spend: -50_000, per_vnd: null, pct: null, status: "giam_chi", below_one: false } });
    const eff = fiveCards(f, 10)[1]!;
    expect(eff.value).toBe("giảm chi");
    expect(eff.tone).toBe("up");
  });

  it("withholds every difference when the previous period has no order lines", () => {
    const f = five({ comparison: { available: false, reason: "no_order_lines_in_previous_period" } });
    const cards = fiveCards(f, 10);
    expect(cards[0]!.chip).toBe("—");
    expect(cards[1]!.sub1).toBe("Chưa có kỳ trước để so");
    expect(cards[3]!.chip).toBe("—");
  });

  it("flags a margin under the target and a spend over the cap", () => {
    const f = five({ spend_cap: { spend_per_day: 1_300_000, cap: 1_200_000, remaining: -100_000, used_pct: 108, over_cap: true } });
    const cards = fiveCards(f, 22);
    expect(cards[2]!.tone).toBe("down");
    expect(cards[2]!.sub2).toBe("Mục tiêu 22%: chưa đạt");
    expect(cards[5]!.tone).toBe("down");
    expect(cards[5]!.sub2).toBe("Vượt trần 100.000đ");
  });
});

describe("freshness", () => {
  it("is fresh when every source covers the window", () => {
    const ov = overview();
    expect(isStale(ov.data, ov.period.window)).toBe(false);
    expect(freshnessOf(ov.data, ov.period.window).every((s) => s.ok)).toBe(true);
  });

  it("is stale when a source covers fewer days than the window", () => {
    const ov = overview({ data: { ...overview().data, ads_daily: { days_covered: 24 } } });
    expect(isStale(ov.data, ov.period.window)).toBe(true);
    expect(freshnessOf(ov.data, ov.period.window).find((s) => s.key === "ads_daily")?.ok).toBe(false);
  });
});
