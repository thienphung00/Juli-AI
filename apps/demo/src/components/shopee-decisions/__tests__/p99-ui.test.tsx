import { readFileSync } from "node:fs";
import { join } from "node:path";

import { configure, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { P_GLOVE, fakeBuilder, pickerProducts } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { plan } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { BuilderToday } from "../../../lib/shopee-decisions/builder-api";
import type { AdsResponse, BuilderP98Api } from "../../../lib/shopee-decisions/builder-p98-api";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import type { PlanCardResult, PlanResponse } from "../../../lib/shopee-decisions/plan-types";
import { AdsBuilder, planDays } from "../ads-builder";
import { TodayLine } from "../builder-p92/compare";
import { OutcomeBody } from "../builder-p92/results";
import { hostOf } from "./harness";
import { RecoHostProvider } from "../../../lib/shopee-decisions/context";

configure({ asyncUtilTimeout: 4000 });

const col = { views: null, ctr: null, ctor: null, orders: 0, aov: null, gmv: 0, profit: null, by_source: {} };
const notEstimable = (label: string, over: Partial<OptionResult> = {}): OptionResult => ({
  kind: "ads_new",
  label,
  days: 30,
  horizon: "first_30_days",
  drivers: ["views"],
  estimable: false,
  basis: "not_estimable",
  basis_weak: false,
  delta: { profit: null, gmv: { value: null, pct: null }, orders: { value: null, pct: null, note: "chưa ước tính được — cần chạy thử" } },
  build_up: [],
  drivers_pct: [],
  cost: { total: 3_000_000, break_even_orders: 24.2, break_even_aov: null, text: "Ngân sách 100.000đ × 30 ngày" },
  after: { days: 30, label: "30 ngày đầu", gmv_before: 0, gmv_after: null, profit_before: null, profit_after: null },
  per_30d: { profit: null, gmv: null, orders: null },
  detail: { before: col, low: null, likely: null, high: null },
  notes: [],
  ...over,
});

describe("P99 Ads tab: Chọn / Thêm vào kế hoạch from the setup row's spec", () => {
  const spec = { kind: "ads_new", campaign: "group", item_ids: [P_GLOVE], daily_budget: 100_000, start: "2026-11-10" };
  const out: AdsResponse = { as_of: "2026-11-10", budget_minimum: 100_000, setups: [{ campaign: "group", campaign_label: "Chiến dịch nhóm", name: null, daily_budget: 100_000, days: null, total_budget: null, products: [], result: notEstimable("Ads"), spec }] };
  const api = { ads: () => Promise.resolve(out) } as unknown as BuilderP98Api;

  function setup() {
    const b = fakeBuilder();
    const reco = fakeReco({});
    render(
      <RecoHostProvider host={hostOf(reco, { builder: b })}>
        <AdsBuilder api={api} products={pickerProducts().products} />
      </RecoHostProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Găng tay cao su A" }));
    fireEvent.change(screen.getByLabelText("Ngày bắt đầu 1"), { target: { value: "2026-11-10" } });
    fireEvent.click(screen.getByTestId("ads-calc"));
    return b;
  }

  it("shows the not-estimable card with its cost and break-even, never +0", async () => {
    setup();
    const card = await screen.findByTestId("option-card");
    expect(card).toHaveTextContent("—");
    expect(card).toHaveTextContent("3.000.000đ");
    expect(screen.getByTestId("oc-breakeven")).toHaveTextContent("cần thêm 25 đơn để hoà vốn");
    expect(screen.getByTestId("oc-orders")).not.toHaveTextContent("+0");
  });

  it("'Thêm vào kế hoạch' sends the spec to group (30-day horizon without an end date); 'Chọn' to choose", async () => {
    const b = setup();
    fireEvent.click(await screen.findByTestId("ads-plan-0"));
    await waitFor(() => expect(screen.getByTestId("ads-done-0")).toHaveTextContent("Đã thêm vào Kế hoạch"));
    const g = b.calls.find((c) => c.name === "group")!.args[0] as { versions: unknown[]; members: number[]; days: number; start: string };
    expect(g.versions).toEqual([spec]);
    expect(g).toMatchObject({ members: [0], days: 30, start: "2026-11-10" });
    fireEvent.click(screen.getByTestId("ads-choose-0"));
    await waitFor(() => expect(b.calls.some((c) => c.name === "choose")).toBe(true));
    expect((b.calls.find((c) => c.name === "choose")!.args[0] as { versions: unknown[] }).versions).toEqual([spec]);
  });

  it("a group runs 3 to 90 days", () => {
    expect([planDays(null), planDays(1), planDays(7), planDays(400)]).toEqual([30, 3, 7, 90]);
  });
});

describe("P99 Affiliate: the single-product commission card is the OptionResult card", () => {
  it("draws cost, break-even and the not-estimable label from `result`", () => {
    const o = { index: 0, kind: "affiliate", label: "Hoa hồng 10%", ok: true, result: notEstimable("Hoa hồng 10%", { kind: "affiliate_commission", notes: ["Lợi nhuận mỗi đơn tính trên 12 ngày có dữ liệu chi phí (trong 30 ngày)"] }) };
    render(<OutcomeBody costLink="/x" outcome={o} />);
    expect(screen.getByTestId("option-card")).toBeInTheDocument();
    expect(screen.getByTestId("oc-cost")).toHaveTextContent("3.000.000đ");
    expect(screen.getByTestId("oc-gmv")).toHaveTextContent("—");
    expect(screen.getByTestId("oc-cost-days")).toHaveTextContent("12 ngày có dữ liệu chi phí");
    expect(screen.queryByTestId("p2-dgmv")).toBeNull();
  });
});

describe("P99 So sánh 'Hôm nay' by scope", () => {
  const base: BuilderToday = { scope: "product", items: [P_GLOVE], gmv_30d: 6_000_000, orders_30d: 550, aov: 12_500, margin_pct: 26.6, window: { from: "2026-10-11", to: "2026-11-09", days: 30 } };
  it("a product scope shows the product's figures", () => {
    render(<TodayLine today={base} />);
    const t = screen.getByTestId("p2-today");
    expect(t).toHaveTextContent("Hôm nay (sản phẩm, 30 ngày): 550 đơn · GMV 6.000.000đ · biên 26,6% · AOV 12.500đ");
    expect(screen.queryByTestId("p2-today-mixed")).toBeNull();
  });
  it("a shop scope says cả shop", () => {
    render(<TodayLine today={{ ...base, scope: "shop", orders_30d: 97 }} />);
    expect(screen.getByTestId("p2-today")).toHaveTextContent("Hôm nay (cả shop, 30 ngày): 97 đơn");
  });
  it("mixed scopes show the shop figures", () => {
    render(<TodayLine today={{ ...base, scope: "shop", mixed_scopes: true }} />);
    expect(screen.getByTestId("p2-today")).toHaveTextContent("cả shop");
  });
});

describe("P99 builder tabs: selected label stays legible", () => {
  const css = readFileSync(join(__dirname, "../../../app/shopee-p91.css"), "utf8");
  const rule = (sel: string) => css.slice(css.indexOf(sel)).split("}")[0] ?? "";
  it("the tabs use packages/theme tokens only, selected text contrasts with its fill", () => {
    const on = rule(".p98-modes .sb-pill--on");
    expect(on).toContain("background: var(--juli-primary-text)");
    expect(on).toContain("color: var(--juli-background)");
    expect(on).not.toMatch(/#[0-9a-f]{3,8}/i);
    expect(rule(".p98-modes .sb-pill {")).not.toMatch(/#[0-9a-f]{3,8}/i);
  });
});
