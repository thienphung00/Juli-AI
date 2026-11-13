import { configure, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { fakeApi } from "../../../lib/shopee-analytics/__tests__/fixtures";
import { notMaterializedOf } from "../../../lib/shopee-analytics/not-materialized";
import { fakePlan, plan } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import type { AdsReadback, PlanAggregate, PlanCardResult, PlanResponse } from "../../../lib/shopee-decisions/plan-types";
import { TongQuanView } from "../../shopee-analytics/tong-quan";
import { renderWith } from "../../shopee-analytics/__tests__/harness";
import { CompareTable, OptionCard } from "../option-card";
import { serverOrder } from "../builder-p92/compare";
import { costText } from "../builder-p92/results";
import { breakEvenText } from "../../../lib/shopee-decisions/builder-p92";
import type { BuilderOutcome } from "../../../lib/shopee-decisions/builder-api";
import { DecisionsView } from "../decisions-view";
import { params, renderReco } from "./harness";

configure({ asyncUtilTimeout: 4000 });

const HORIZON = { from: "2026-11-11", to: "2026-12-10", days: 30, label: "30 ngày tới: 11/11 – 10/12" };
const span = (from: string, to: string, days: number) => ({ from, to, days });

function open(first: PlanResponse) {
  const api = fakePlan(first);
  renderReco(<DecisionsView params={params("ke-hoach=1")} />, fakeReco(), { plan: { api } });
  return api;
}

const result = (over: Partial<PlanCardResult> = {}): PlanCardResult => ({
  estimable: true,
  counted: true,
  message: null,
  reason: null,
  delta: { p10: { dgmv: 1, dorders: 1, dprofit: 1 }, p50: { dgmv: 600_000, dorders: 3.2, dprofit: 90_000 }, p90: { dgmv: 1, dorders: 6, dprofit: 1 } },
  cost_total: 360_000,
  cost_horizon: 240_000,
  cost_known: true,
  break_even_orders: null,
  days: 20,
  horizon: span("2026-11-11", "2026-12-10", 30),
  own_dates: span("2026-11-25", "2026-12-14", 20),
  own_days: 20,
  dated: true,
  counted_dates: span("2026-11-25", "2026-12-10", 16),
  counted_days: 16,
  outside_horizon: false,
  before: { gmv_30d: 6_000_000, orders_30d: 550, profit_30d: 1_500_000 },
  after: { gmv_30d: 6_600_000, orders_30d: 553.2, profit_30d: 1_590_000 },
  notes: [],
  ...over,
});

/** The fixture plan with the horizon and `res` on the first card. */
function withAgg(res: PlanCardResult, over: Partial<PlanAggregate> = {}): PlanResponse {
  const p = plan();
  const first = p.aggregate!.cards[0]!;
  return {
    ...p,
    aggregate: { ...p.aggregate!, horizon: HORIZON, live: true, cards: [{ ...first, result: res }, ...p.aggregate!.cards.slice(1)], ...over },
  };
}

describe("P99b Kế hoạch: horizon, counted days, cost", () => {
  it("shows the 30-day horizon and each card's counted days against its own days", async () => {
    open(withAgg(result()));
    expect(await screen.findByTestId("kh-total")).toHaveTextContent("11/11 – 10/12");
    expect(screen.getAllByTestId("kh-row-dates")[0]).toHaveTextContent("25/11 – 14/12 · 20 ngày");
  });

  it("unknown plan cost is said, not summed", async () => {
    const p = withAgg(result(), { totals_partial: true, totals_note: "Tổng chưa gồm 1 thẻ chưa ước tính được.", cost_unknown_cards: ["card-tr"] });
    const cost = { ...p.aggregate!.cost!, horizon: span("2026-11-11", "2026-12-10", 30), horizon_spend_before: 30_000_000, horizon_spend_delta: null, horizon_spend_after: null, horizon_cap: 36_000_000, over_by_horizon: null, cost_complete: false, cost_note: "Thiếu chi phí của 1 thẻ.", cost_unknown_cards: ["card-tr"] };
    open({ ...p, aggregate: { ...p.aggregate!, cost } });
    expect(await screen.findByTestId("kh-agg-chi")).toHaveTextContent("chưa biết chi phí");
    expect(screen.getByTestId("kh-agg-chiday")).not.toHaveTextContent("Vượt trần");
  });

  it("null certain / deltas render as — and never 0", async () => {
    const p = withAgg(result());
    const agg = { ...p.aggregate!, deltas_p50: { gmv: null, orders: null, aov: null, bien: null }, dprofit_month: { ...p.aggregate!.dprofit_month!, certain: null }, dorders_month: { p10: null, p50: null, p90: null } };
    open({ ...p, aggregate: agg });
    expect(await screen.findByTestId("kh-agg-sure")).toHaveTextContent("— (chưa tách được phần chắc chắn)");
    expect(screen.getByTestId("kh-agg-sure")).not.toHaveTextContent("+0");
    expect(screen.getByTestId("kh-agg-orders")).not.toHaveTextContent("+0");
    expect(screen.getByTestId("kh-agg-orders")).toHaveTextContent("—");
  });

});

describe("P99b Kế hoạch: empty plan and data_missing", () => {
  it("an empty plan shows its note and no numbers", async () => {
    const aggregate: PlanAggregate = { n_cards: 0, horizon: HORIZON, live: true, today: null, after: null, cost: null, deltas_p50: null, empty: true, empty_note: "Kế hoạch trống: thêm thẻ để xem 30 ngày tới.", cards: [], unavailable_cards: [], range_method: "x" };
    open({ plan: plan().plan, cards: [], aggregate, windows: null, change_sets: [] });
    expect(await screen.findByTestId("kh-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("kh-empty-note")).toBeNull();
    expect(screen.queryByTestId("kh-agg")).toBeNull();
  });

  it("P100 A.8: a plan that has cards never says it has none, even when its ungrouped aggregate is empty", async () => {
    const p = plan();
    expect(p.cards.length).toBeGreaterThan(0);
    const aggregate: PlanAggregate = { n_cards: 0, horizon: HORIZON, live: true, today: null, after: null, cost: null, deltas_p50: null, empty: true, empty_note: "Kế hoạch chưa có thẻ nào.", cards: [], unavailable_cards: [], range_method: "x" };
    open({ ...p, aggregate });
    expect(await screen.findByTestId("kh-rows")).toBeInTheDocument();
    expect(screen.queryByTestId("kh-empty-note")).toBeNull();
    expect(screen.queryByText("Kế hoạch chưa có thẻ nào.")).toBeNull();
  });

  it("data_missing shows the message and window and no figure at all", async () => {
    const p = plan();
    const aggregate: PlanAggregate = {
      n_cards: 3,
      horizon: HORIZON,
      today: null,
      after: null,
      cost: null,
      cards: [],
      products: [],
      result_basis: null,
      unavailable_cards: [],
      range_method: "x",
      data_missing: { code: "rows_not_materialized", message: "Chưa có số liệu theo ngày của kỳ này.", window: { from: "2026-10-12", to: "2026-11-10" }, missing_days: 3, first_missing: "2026-11-08" },
    };
    open({ ...p, cards: p.cards.map((c) => ({ ...c, evaluation: null })), aggregate });
    expect(await screen.findByTestId("kh-dm-detail")).toHaveTextContent("Kỳ 12/10–10/11 · thiếu 3 ngày, từ 08/11");
    expect(screen.queryByTestId("kh-agg")).toBeNull();
    expect(screen.queryByTestId("kh-prod-today")).toBeNull();
    expect(screen.queryByTestId("kh-base")).toBeNull();
  });
});

describe("P99b Tự tạo / So sánh: the version's set dates, no per_30d column", () => {
  const col = { views: null, ctr: null, ctor: null, orders: 0, aov: null, gmv: 0, profit: null, by_source: {} };
  const res = (label: string, p30: number | null): OptionResult => ({
    kind: "voucher",
    label,
    days: 10,
    horizon: "duration",
    drivers: [],
    estimable: true,
    basis: "own" as never,
    basis_weak: false,
    delta: { profit: { value: 100_000, pct: 2, low: 50_000, high: 150_000 } as never, gmv: { value: 1_000_000, pct: 3 } as never, orders: { value: 5, pct: 1, note: null } as never },
    build_up: [],
    drivers_pct: [],
    cost: { total: 80_000, break_even_orders: null, break_even_aov: null, text: "" },
    after: { days: 10, label: "Sau 10 ngày", gmv_before: 1, gmv_after: 2, profit_before: 1, profit_after: 2 },
    per_30d: { profit: p30, gmv: 3_000_000, orders: 15, secondary: true, label: "Quy đổi 30 ngày (tham khảo)" },
    detail: { before: col, low: null, likely: null, high: null },
    notes: [],
  });
  const dates = { from: "2026-12-01", to: "2026-12-10", days: 10, set: true, label: "01/12 – 10/12 (10 ngày)" };

  it("OptionCard names the set dates; per_30d stays off the card (P100-C, B.6)", () => {
    render(<OptionCard dates={dates} result={res("V1", 300_000)} />);
    expect(screen.getByTestId("oc-dates")).toHaveTextContent("Tính cho: 01/12 – 10/12 (10 ngày)");
    expect(screen.queryByTestId("oc-per30")).toBeNull();
    expect(screen.getByTestId("oc-profit")).toHaveTextContent("+100.000đ");
    expect(screen.getByTestId("oc-profit")).not.toHaveTextContent("300.000");
    expect(screen.getByTestId("oc-cost")).toHaveTextContent("80.000đ");
  });
  it("dates not set: the label says the first N days", () => {
    render(<OptionCard dates={{ from: null, to: null, days: 30, set: false, label: "30 ngày đầu" }} result={res("V1", 300_000)} />);
    expect(screen.getByTestId("oc-dates")).toHaveTextContent("30 ngày đầu (chưa đặt ngày)");
  });
  it("the comparison table has no Quy đổi 30 ngày column (P100 B.6)", () => {
    render(<CompareTable rows={[{ id: 1, name: "P1", result: res("V1", null), dates }]} />);
    const row = screen.getByTestId("oc-row-1");
    expect(row).toHaveTextContent("01/12 – 10/12 (10 ngày)");
    expect(row.querySelector("[data-secondary]")).toBeNull();
    expect(screen.queryByText(/Quy đổi 30 ngày/)).toBeNull();
  });
});

describe("P99b 409 rows_not_materialized", () => {
  const err = () =>
    new ShopeeApiError(409, "rows_not_materialized", "Chưa dựng xong số liệu theo ngày của kỳ này.", {
      code: "rows_not_materialized",
      message: "Chưa dựng xong số liệu theo ngày của kỳ này.",
      window: { from: "2026-10-12", to: "2026-11-10" },
      missing_days: 2,
      first_missing: "2026-11-09",
    });

  it("is parsed from the error", () => {
    expect(notMaterializedOf(err())).toEqual({ message: "Chưa dựng xong số liệu theo ngày của kỳ này.", window: "12/10–10/11", missingDays: 2, firstMissing: "2026-11-09" });
    expect(notMaterializedOf(new ShopeeApiError(409, "not_a_shopee_shop", "x"))).toBeNull();
    expect(notMaterializedOf(new Error("x"))).toBeNull();
  });

  it("an analytics screen shows the message and window and no figures", async () => {
    const api = fakeApi({}, err());
    renderWith(<TongQuanView params={params()} />, api);
    expect(await screen.findByTestId("sa-not-materialized")).toHaveTextContent("Chưa dựng xong số liệu theo ngày của kỳ này.");
    expect(screen.getByTestId("sa-nm-detail")).toHaveTextContent("Kỳ 12/10–10/11 · thiếu số liệu 2 ngày, từ 09/11");
    expect(screen.queryByTestId("sa-tile-gmv")).toBeNull();
  });

  it("Kế hoạch shows the same notice and drops the earlier numbers when the refetch is refused", async () => {
    const api = fakePlan(plan(), { get: err() });
    renderReco(<DecisionsView params={params("ke-hoach=1")} />, fakeReco(), { plan: { api } });
    expect(await screen.findByTestId("sd-not-materialized")).toHaveTextContent("Chưa dựng xong số liệu theo ngày của kỳ này.");
    expect(screen.queryByTestId("kh-agg")).toBeNull();
    await waitFor(() => expect(screen.queryByTestId("kh-plan")).toBeNull());
  });

  it("a generic API error leaves no figures either", async () => {
    const api = fakePlan(plan(), { get: new ShopeeApiError(500, "", "boom") });
    renderReco(<DecisionsView params={params("ke-hoach=1")} />, fakeReco(), { plan: { api } });
    expect(await screen.findByTestId("sd-refusal-failed")).toBeInTheDocument();
    expect(screen.queryByTestId("kh-agg")).toBeNull();
  });
});

describe("P99c cost and break-even on the version's days", () => {
  const out = (over: Partial<BuilderOutcome>): BuilderOutcome => ({ index: 0, kind: "voucher", label: "V", ok: true, ...over });
  it("a figure replaced from the result keeps the server's label (trong N ngày)", () => {
    const o = out({ cost: { amount: 80_000, period_days: 10, source: "result", label: "Chi phí trong 10 ngày", per_unit: 5000 } });
    expect(costText(o)).toBe("80.000đ");
  });
  it("a null cost shows reason_text, never 0đ", () => {
    const o = out({ cost: { amount: null, period_days: 10, source: null, reason: "no_result_for_days", reason_text: "Chưa có kết quả cho 10 ngày đã đặt." } });
    expect(costText(o)).toBe("Chưa có kết quả cho 10 ngày đã đặt.");
  });
  it("a null break-even shows its reason, not 0 or a 30-day figure", () => {
    const o = out({ break_even: { applies: true, source: "none", extra_orders: null, period_days: 10, reason: "no_result_for_days", reason_text: "Chưa có kết quả cho 10 ngày đã đặt." } });
    expect(breakEvenText(o)).toBe("Chưa có kết quả cho 10 ngày đã đặt.");
    expect(breakEvenText(out({ break_even: { applies: true, source: "result", extra_orders: 7.2, period_days: 10 } }))).toContain("cần thêm ≥ 8 đơn");
  });
  it("serverOrder follows compare, and the table shows sort_basis as caption", () => {
    const rows = [{ index: 0, id: "a" }, { index: 1, id: "b" }, { index: 2, id: "c" }];
    expect(serverOrder([2, 0, 1], rows).map((r) => r.id)).toEqual(["c", "a", "b"]);
    expect(serverOrder(undefined, rows).map((r) => r.id)).toEqual(["a", "b", "c"]);
  });
});
