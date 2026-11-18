import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { deltaOf, hasCost, metricsFor, profitVerdict, reasonLine, strategyOf } from "../../../lib/shopee-decisions/card-rows";
import type { FunnelColumn, OptionResult } from "../../../lib/shopee-decisions/option-result";
import { ResultCard } from "../builder-p92/results";

const col = (gmv: number, profit: number, orders: number): FunnelColumn => ({ views: 1000, ctr: 3, ctor: 4, orders, aov: 100000, gmv, profit, by_source: {} });

function result(kind: string, over: Partial<OptionResult> = {}): OptionResult {
  return {
    kind,
    label: "x",
    days: 7,
    horizon: "duration",
    drivers: ["aov"],
    estimable: true,
    basis: "shop",
    basis_weak: false,
    delta: { profit: { value: 12000, pct: null, low: null, high: null }, gmv: { value: 80000, pct: null }, orders: { value: 2, pct: null, note: null } },
    build_up: [],
    drivers_pct: [],
    cost: { total: 0, break_even_orders: null, break_even_aov: null, text: "" },
    after: { days: 7, label: "7 ngày", gmv_before: 1, gmv_after: 1, profit_before: 1, profit_after: 1 },
    per_30d: { profit: null, gmv: null, orders: null },
    detail: { before: col(1000000, 100000, 10), low: null, likely: col(1080000, 112000, 12), high: null },
    notes: [],
    ...over,
  };
}

describe("kind -> rows (U1)", () => {
  it("maps kinds to strategies", () => {
    expect(["title", "cover_image", "description_first_line"].map((k) => strategyOf(k))).toEqual(["listing", "listing", "listing"]);
    expect(["min_spend_voucher", "add_on", "gift", "product_discount", "price", "bundle_deal"].every((k) => strategyOf(k) === "offer")).toBe(true);
    expect(strategyOf("ads_budget")).toBe("ads");
    expect(strategyOf("affiliate_commission")).toBe("affiliate");
  });

  it("an offer without a cost has no Chi phí / hoà vốn column; with a cost it has both and the return", () => {
    expect(metricsFor([result("min_spend_voucher")])).toEqual(["gmv", "profit", "orders", "margin"]);
    const costly = result("min_spend_voucher", { cost: { total: 50000, break_even_orders: 3, break_even_aov: null, text: "" }, roi: { value: 1.6, text: null } });
    expect(hasCost(costly)).toBe(true);
    expect(metricsFor([costly])).toEqual(["gmv", "profit", "cost", "orders", "margin", "breakeven", "roi"]);
  });

  it("a listing change has no money column at all; its estimate gives views / CTR only", () => {
    expect(metricsFor([result("description_first_line", { estimable: false, reason_text: "Chưa có từ khoá" })])).toEqual([]);
    const est = result("title", { drivers_pct: [{ metric: "views", label: "Lượt xem", pct: 4.2 }, { metric: "ctr", label: "CTR", pct: null }] });
    expect(metricsFor([est])).toEqual(["views"]);
    expect(reasonLine(result("title", { estimable: false, reason_text: "Chưa có từ khoá" }))).toBe("Chưa có từ khoá");
  });

  it("'Có lãi' only when Δ lợi nhuận is above zero", () => {
    const zero = result("min_spend_voucher", { delta: { ...result("x").delta, profit: { value: 0, pct: null, low: null, high: null } } });
    expect(profitVerdict(zero)).toEqual({ text: "Không đổi", tone: "flat" });
    expect(profitVerdict(result("min_spend_voucher")).text).toBe("Có lãi");
  });
});

describe("F5 (b): a within-noise amount keeps its P50 and the tag, never '—'", () => {
  const noisy = result("min_spend_voucher", {
    within_noise: ["gmv", "profit"],
    delta: { profit: null, gmv: { value: null, pct: null }, orders: { value: 2, pct: null, note: null } },
  });

  it("rebuilds the P50 from the likely and before columns", () => {
    expect(deltaOf(noisy, "gmv")).toEqual({ value: 80000, noise: true });
    expect(deltaOf(noisy, "profit")).toEqual({ value: 12000, noise: true });
  });

  it("the result card shows the amount followed by the tag", () => {
    render(<ResultCard name="P1" result={noisy} />);
    expect(screen.getByTestId("p3-dgmv")).toHaveTextContent("+80.000đ · trong dao động");
    expect(screen.getByTestId("p3-dprofit")).toHaveTextContent("+12.000đ · trong dao động");
    expect(screen.getByTestId("p3-dgmv")).not.toHaveTextContent("—");
  });
});
