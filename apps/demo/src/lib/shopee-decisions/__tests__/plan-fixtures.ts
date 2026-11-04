import type { FiveNumbers } from "../../shopee-analytics/types";
import type { Brief, MeasurementCut, PlanApi, PlanBreach, PlanCard, PlanEvaluation, PlanResponse, PlanVersion, WindowProductRow } from "../plan-types";

/** Synthetic plan of "Shop mẫu gia dụng" in the shape the backend answers (`plans.get_plan`); no shop data. */

const brief = (certain: number, p10: number, p50: number, p90: number, over: Partial<Brief> = {}): Brief => ({
  dprofit: { certain, p10, p50, p90 },
  dgmv: { certain: 0, p50: p50 * 6 },
  dorders_p50: 3,
  cost_month: -certain,
  floor_ok: true,
  ...over,
});

const ver = (version: number, code: string, label: string, status = "ok"): PlanVersion => ({ version, code: `${code}-V${version}`, label, status, ranked: version === 1, inputs: {}, floor_ok: status !== "floor_breach", dprofit_month_p50: 90_000, dgmv_month_p50: 600_000 });

function evaluation(card: Pick<PlanCard, "card_id" | "code" | "product_id" | "change_kind" | "title">, contribution: number, over: Partial<PlanEvaluation> = {}): PlanEvaluation {
  return {
    card_id: card.card_id,
    code: card.code,
    title: card.title ?? "",
    family: "voucher",
    change_kind: card.change_kind ?? "voucher",
    product_id: card.product_id,
    version: 1,
    version_label: "Mặc định của Juli",
    inputs: {},
    what_if: {},
    in_joint_layer: true,
    alone: brief(-contribution, 0, contribution, contribution * 3),
    contribution: { dprofit_certain: -contribution, dprofit_p50: contribution, dgmv_p50: contribution * 6, cost_month: contribution },
    without: { ...brief(0, 0, 0, 0), delta: { dprofit_p50: contribution, dgmv_p50: contribution * 6, cost_month: contribution } },
    floor_ok: true,
    breaches: [],
    ...over,
  };
}

export function planCard(over: Partial<PlanCard> = {}, contribution = 90_000): PlanCard {
  const base: PlanCard = {
    card_id: "card-voucher",
    code: "JC-2611-0007",
    plan_code: null,
    status: "planned",
    product_id: "GT-A",
    title: "Voucher 15.000đ cho đơn ≥ 299.000đ",
    family: "voucher",
    change_kind: "voucher",
    chosen_version: 1,
    chosen_version_code: "JC-2611-0007-V1",
    versions: [ver(1, "JC-2611-0007", "15.000đ cho đơn ≥ 299.000đ"), ver(2, "JC-2611-0007", "10.000đ cho đơn ≥ 249.000đ"), ver(3, "JC-2611-0007", "20.000đ cho đơn ≥ 199.000đ", "floor_breach")],
    what_if: {},
    added_at: "2026-11-04T01:00:00",
    added_by: { kind: "seller" },
    acknowledged_breaches: null,
    evaluation: null,
  };
  const merged = { ...base, ...over };
  return { ...merged, evaluation: over.evaluation === undefined ? evaluation(merged, contribution) : over.evaluation };
}

const cards = (): PlanCard[] => [
  planCard(),
  planCard({ card_id: "card-promo", code: "JC-2611-0012", title: "Khuyến mãi 8%", family: "promotion", change_kind: "promotion", chosen_version_code: "JC-2611-0012-V1", versions: [ver(1, "JC-2611-0012", "Khuyến mãi 8%"), ver(2, "JC-2611-0012", "Khuyến mãi 7%")] }, 115_000),
  planCard({ card_id: "card-tr", code: "JC-2611-0003", product_id: "TR-B", title: "Khuyến mãi 12%", family: "promotion", change_kind: "promotion", chosen_version_code: "JC-2611-0003-V1", versions: [ver(1, "JC-2611-0003", "Khuyến mãi 12%")] }, 50_000),
];

const FIVE: FiveNumbers = {
  discount: { vnd_before: 1_248_000, vnd_after: 1_380_000, pct_before: 4.85, pct_after: 5.21 },
  extra_revenue_per_extra_spend: { extra_revenue: 950_000, extra_spend: 1_500_000, per_vnd: 0.63, pct: 63, status: "per_vnd", below_one: true },
  margin: { profit_before: 3_373_000, profit_after: 3_450_000, pct_before: 13.1, pct_after: 12.6, is_partial: false, cost_coverage_pct: 100 },
  orders: { before: 205, after: 214, change_pct: 4.4 },
  aov: { before: 125_610, after: 124_766, change_pct: -0.7 },
  spend_cap: { spend_per_day: 1_090_000, cap: 1_200_000, remaining: 110_000, used_pct: 90.8, over_cap: false },
  chi_definition: "chi = quảng cáo + voucher + khuyến mãi + combo + hoa hồng",
  comparison: { available: true, reason: null },
};

const preset = (days: number, mde_pct: number, recommended: boolean) => ({ days, mde: mde_pct / 100, mde_pct, ok: mde_pct <= 30, hard: mde_pct > 30, label: `${days} ngày: chỉ thấy thay đổi ≥ ${mde_pct} %`, recommended });
const opts = (a: number, b: number, c: number) => ({ metric: "orders", min_days: 3, max_days: 90, presets: [preset(7, a, false), preset(14, b, false), preset(28, c, true)], recommended_days: 28, default_days: 28 });

const winRow = (product_id: string, name: string, mdes: [number, number, number], over: Partial<WindowProductRow> = {}): WindowProductRow => ({ product_id, name, days: 28, source: "auto", recommended_days: 28, options: opts(...mdes), orders_per_day: 4.5, hard: false, ...over });

export const CUTS: readonly MeasurementCut[] = [
  { product_id: "GT-A", name: "Găng tay cao su A", change_set: "set-1", started_on: "2026-10-27", days_measured: 8, window_days: 14, state: "kept_partial", label: "Đo được 8 ngày", days: 8, low_confidence: true },
  { product_id: "TR-B", name: "Túi rác sinh học B", change_set: "set-2", started_on: "2026-11-02", days_measured: 2, window_days: 7, state: "inconclusive", label: "Không kết luận", days: 2, low_confidence: true },
];

export const STACK_BREACH: PlanBreach = { type: "floor", sku: "GT-A-1", kind: "operating", floor: 275_000, min_unit_price: 260_000, stacked: true, card_ids: [], only_when_stacked: true };
const SPEND_BREACH: PlanBreach = { type: "spend_cap", spend_per_day_after: 1_290_000, cap: 1_200_000, over_by_per_day: 90_000 };

export function plan(over: Partial<PlanResponse> = {}): PlanResponse {
  const cs = cards();
  return {
    plan: {
      id: "plan-1",
      status: "draft",
      code: null,
      as_of: "2026-11-04",
      window_days: null,
      product_windows: {},
      planned_date: null,
      created_by: { kind: "seller" },
      created_at: "2026-11-04T01:00:00",
      confirmed_by: null,
      confirmed_at: null,
      executed_at: null,
      acknowledged_breaches: null,
      measurement_cut: [...CUTS],
    },
    cards: cs,
    aggregate: {
      as_of: "2026-11-04",
      n_cards: 3,
      today: { as_of: "2026-11-04", gmv_30d: 25_750_000, orders_30d: 205, aov: 125_610, margin_pct: 13.1 },
      after: { gmv_30d: 26_700_000, orders_30d: 214, aov: 124_766, margin_pct: 12.6, label: "Dự kiến (P50)" },
      deltas_p50: { gmv: 950_000, orders: 9, aov: -844, bien: -0.5 },
      five_numbers: FIVE,
      dprofit_month: { certain: -246_000, predicted: { p10: 276_000, p50: 396_000, p90: 666_000 }, total: { p10: 30_000, p50: 150_000, p90: 420_000 } },
      dgmv_month: { certain: 0, total: { p10: 350_000, p50: 950_000, p90: 1_550_000 } },
      dorders_month: { p10: 4, p50: 9, p90: 15 },
      cost: { per_day_before: 1_040_000, per_day_after: 1_090_000, delta_per_day: 50_000, per_month_after: 32_700_000, delta_per_month: 1_500_000, cap_per_day: 1_200_000, over_cap: false, over_by_per_day: 0, label: "Chi phí = quảng cáo + voucher + khuyến mãi + combo + hoa hồng" },
      floor: { ok: true, breaches: [] },
      breaches: [],
      stacked_products: [{ product_id: "GT-A", cards: ["card-voucher", "card-promo"], codes: ["JC-2611-0007", "JC-2611-0012"], count: 2, stacked_on_same_orders: true }],
      cards: cs.map((c) => c.evaluation!),
      products: [
        { product_id: "GT-A", name: "Găng tay cao su A", cards: ["card-voucher", "card-promo"], codes: ["JC-2611-0007", "JC-2611-0012"], joint: brief(-205_000, 20_000, 100_000, 300_000), predicted_rel_gmv: {}, base_gmv_30d: 15_000_000, orders_per_day: 4.5, window: opts(45, 32, 23) },
        { product_id: "TR-B", name: "Túi rác sinh học B", cards: ["card-tr"], codes: ["JC-2611-0003"], joint: brief(-41_000, 0, 50_000, 120_000), predicted_rel_gmv: {}, base_gmv_30d: 8_000_000, orders_per_day: 2.1, window: opts(60, 42, 30) },
      ],
      shop_wide: null,
      joint_cards: ["card-voucher", "card-promo"],
      added_cards: ["card-tr"],
      profit_unknown_cards: [],
      unavailable_cards: [],
      notes: [],
      range_method: "root_sum_squares",
    },
    windows: {
      plan_default_days: null,
      plan_default_source: "auto",
      min_days: 3,
      max_days: 90,
      presets: [7, 14, 28],
      per_product: [winRow("GT-A", "Găng tay cao su A", [45, 32, 23]), winRow("TR-B", "Túi rác sinh học B", [60, 42, 30])],
    },
    change_sets: [],
    ...over,
  };
}

/** The plan with the two cards of GT-A stacking under the floor (each fine alone). */
export function stackedPlan(): PlanResponse {
  const p = plan();
  return { ...p, aggregate: { ...p.aggregate!, floor: { ok: false, breaches: [STACK_BREACH] }, breaches: [STACK_BREACH] } };
}

/** The plan with the shop-wide spend over its cap. */
export function overCapPlan(): PlanResponse {
  const p = plan();
  return { ...p, aggregate: { ...p.aggregate!, cost: { ...p.aggregate!.cost!, per_day_after: 1_290_000, over_cap: true, over_by_per_day: 90_000 }, breaches: [SPEND_BREACH] } };
}

/** The plan once confirmed: code issued, every card approved, the cut measurements kept on it. */
export function confirmedPlan(code = "KH-2611-003", plannedDate = "2026-11-05"): PlanResponse {
  const p = plan();
  return {
    ...p,
    plan: { ...p.plan!, status: "confirmed", code, planned_date: plannedDate, confirmed_at: "2026-11-04T02:00:00", confirmed_by: { kind: "seller" } },
    cards: p.cards.map((c) => ({ ...c, status: "approved", plan_code: code })),
    measurement_cut: [...CUTS],
  };
}

export const emptyPlan = (): PlanResponse => ({ plan: null, cards: [], aggregate: null, windows: null, change_sets: [] });

export interface FakePlan extends PlanApi {
  readonly calls: { readonly name: string; readonly args: unknown[] }[];
}

type Next = Partial<Record<keyof PlanApi, PlanResponse | Error | ((...a: never[]) => PlanResponse)>>;

/** Every method resolves with the given plan (`next` can change it per call); `calls` records name and arguments. */
export function fakePlan(first: PlanResponse = plan(), next: Next = {}): FakePlan {
  const calls: { name: string; args: unknown[] }[] = [];
  const run = (name: keyof PlanApi, ...args: unknown[]): Promise<PlanResponse> => {
    calls.push({ name, args });
    const n = next[name];
    if (n instanceof Error) return Promise.reject(n);
    return Promise.resolve(typeof n === "function" ? (n as (...a: unknown[]) => PlanResponse)(...args) : (n ?? first));
  };
  return {
    calls,
    get: () => run("get"),
    add: (...a) => run("add", ...a),
    remove: (...a) => run("remove", ...a),
    setVersion: (...a) => run("setVersion", ...a),
    whatIf: (...a) => run("whatIf", ...a),
    setWindow: (...a) => run("setWindow", ...a),
    confirm: (...a) => run("confirm", ...a),
    setChangeSetWindow: async (id, days) => {
      calls.push({ name: "setChangeSetWindow", args: [id, days] });
      return first.change_sets[0] ?? ({ id, window_days: days } as never);
    },
    changeSets: async (...a) => {
      calls.push({ name: "changeSets", args: a });
      return first.change_sets;
    },
  };
}
