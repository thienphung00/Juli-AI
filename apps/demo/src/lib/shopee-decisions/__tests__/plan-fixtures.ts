import type { Plan, PlanApi, PlanCardRow, PlanSnapshot } from "../plan-types";

/** Synthetic plan of "Shop mẫu gia dụng" (the artboards' numbers; no shop data). */

const snap = (o: Partial<PlanSnapshot> = {}): PlanSnapshot => ({ orders: 205, gmv: 25_750_000, aov: 125_600, discount_rate: 0.0485, margin: 0.131, spend_month: 3_076_000, ...o });

export function planRow(over: Partial<PlanCardRow> = {}): PlanCardRow {
  return {
    card_id: "card-voucher",
    code: "JC-2611-0007",
    product_id: "GT-A",
    product_name: "Găng tay cao su A",
    kind_label: "Voucher",
    chosen_version: 1,
    versions: [
      { version: 1, label: "15.000đ cho đơn ≥ 299.000đ", status: "ok" },
      { version: 2, label: "10.000đ cho đơn ≥ 249.000đ", status: "ok" },
      { version: 3, label: "20.000đ cho đơn ≥ 199.000đ", status: "floor_breach" },
    ],
    label: "15.000đ cho đơn ≥ 299.000đ",
    contribution_p50: 90_000,
    without: { dprofit_month: -90_000, margin_points: -0.2, aov: -2_000 },
    stack_breach: false,
    floor_breach: false,
    ...over,
  };
}

export function plan(over: Partial<Plan> = {}): Plan {
  return {
    id: "plan-1",
    code: null,
    status: "draft",
    cards: [planRow(), planRow({ card_id: "card-promo", code: "JC-2611-0012", kind_label: "Khuyến mãi", label: "Khuyến mãi 8%", chosen_version: 1, versions: [{ version: 1, label: "Khuyến mãi 8%", status: "ok" }, { version: 2, label: "Khuyến mãi 7%", status: "ok" }], contribution_p50: 115_000, without: { dprofit_month: -115_000, margin_points: 0.1, aov: 0 } }), planRow({ card_id: "card-tr", code: "JC-2611-0003", product_id: "TR-B", product_name: "Túi rác sinh học B", kind_label: "Khuyến mãi", label: "Khuyến mãi 12%", versions: [{ version: 1, label: "Khuyến mãi 12%", status: "ok" }], contribution_p50: 50_000 })],
    aggregate: {
      scope: { product_names: ["Găng tay cao su A", "Túi rác sinh học B"], days: 30 },
      today: snap(),
      after: { low: snap({ orders: 209, gmv: 26_100_000, aov: 124_900, discount_rate: 0.0521, margin: 0.126, spend_month: 3_190_000 }), high: snap({ orders: 220, gmv: 27_300_000, aov: 124_100, discount_rate: 0.0543, margin: 0.131, spend_month: 3_260_000 }) },
      dprofit_certain: -246_000,
      dprofit_month: { p10: 30_000, p50: 150_000, p90: 420_000 },
      spend: { per_day_now: 1_040_000, per_day_after: 1_090_000, cap: 1_200_000, over_cap: false },
      floor: { ok: true, breaches: [] },
    },
    stack_breaches: [],
    window: {
      mode: "auto",
      presets: [7, 14, 28],
      mde: { "7": { "GT-A": 45, "TR-B": 60 }, "14": { "GT-A": 32, "TR-B": 42 }, "28": { "GT-A": 23, "TR-B": 30 } },
      products: [
        { product_id: "GT-A", product_name: "Găng tay cao su A", kinds: ["Voucher", "Khuyến mãi"], recommended_days: 28, days: 28, override_days: null, mde_pct: 23 },
        { product_id: "TR-B", product_name: "Túi rác sinh học B", kinds: ["Khuyến mãi"], recommended_days: 28, days: 28, override_days: null, mde_pct: 30 },
      ],
      min_days: 3,
      max_days: 90,
    },
    cuts: [{ product_id: "GT-A", product_name: "Găng tay cao su A", code: "JC-2610-0031", kind_label: "Khuyến mãi", done_days: 8, total_days: 14 }, { product_id: "TR-B", product_name: "Túi rác sinh học B", code: "JC-2610-0027", kind_label: "Quảng cáo", done_days: 2, total_days: 7 }],
    kol: null,
    ...over,
  };
}

export const STACK = {
  product_id: "GT-A",
  product_name: "Găng tay cao su A",
  cards: [{ code: "JC-2611-0007", version: 1, label: "15.000đ cho đơn ≥ 299.000đ" }, { code: "JC-2611-0012", version: 1, label: "Khuyến mãi 8%" }],
  basket: 299_000,
  buyer_pays: 260_000,
  floor: 275_000,
  shortfall: 15_000,
  alone: [{ code: "JC-2611-0007", buyer_pays: 284_000 }, { code: "JC-2611-0012", buyer_pays: 275_000 }],
} as const;

export interface FakePlan extends PlanApi {
  readonly calls: { readonly name: string; readonly args: unknown[] }[];
}

/** Every method resolves with the given plan (`next` can change it per call); `calls` records name and arguments. */
export function fakePlan(first: Plan = plan(), next: Partial<Record<keyof PlanApi, Plan | Error | ((...a: never[]) => Plan)>> = {}): FakePlan {
  const calls: { name: string; args: unknown[] }[] = [];
  const run = (name: keyof PlanApi, ...args: unknown[]): Promise<Plan> => {
    calls.push({ name, args });
    const n = next[name];
    if (n instanceof Error) return Promise.reject(n);
    return Promise.resolve(typeof n === "function" ? (n as (...a: unknown[]) => Plan)(...args) : (n ?? first));
  };
  return {
    calls,
    get: () => run("get"),
    add: (...a) => run("add", ...a),
    remove: (...a) => run("remove", ...a),
    setVersion: (...a) => run("setVersion", ...a),
    setWindow: (...a) => run("setWindow", ...a),
    mde: async (days) => {
      calls.push({ name: "mde", args: [days] });
      return { "GT-A": Math.round(45 * Math.sqrt(7 / days)), "TR-B": Math.round(60 * Math.sqrt(7 / days)) };
    },
    confirm: (...a) => run("confirm", ...a),
  };
}
