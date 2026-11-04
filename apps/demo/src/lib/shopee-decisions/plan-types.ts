import type { Breach, N } from "./types";

/**
 * Draft plan ("Kế hoạch", P91 D-6 / D-7 / D-8) as the UI reads it. The plan backend is built in
 * parallel with this screen: every field below is an ASSUMPTION taken from the artboards
 * (`KeHoach.dc.html`, `KeHoachMobile.dc.html`) and `fasttrack/contracts/p91-plan.md`; the
 * orchestrator reconciles them when the routes land (see the list in the wave-3 report).
 * Routes (under the recommendations prefix, seller and Ops alike):
 *   GET plan · POST plan/cards · DELETE plan/cards/{card_id} · PUT plan/cards/{card_id}
 *   PUT plan/window · GET plan/mde?days=N · POST plan/confirm
 */

export type PlanStatus = "draft" | "confirmed" | "executed";

/** One month-scale snapshot of the plan's scope (the products in it). */
export interface PlanSnapshot {
  readonly orders: number;
  readonly gmv: number;
  readonly aov: N;
  /** % of GMV niêm yết given away (①), as a fraction. */
  readonly discount_rate: N;
  /** Biên on what the buyer pays, as a fraction (③). */
  readonly margin: N;
  readonly spend_month: N;
}

export interface Range<T = N> {
  readonly p10: T;
  readonly p90: T;
}

export interface PlanCardRow {
  readonly card_id: string;
  readonly code: string;
  readonly product_id: string | null;
  readonly product_name: string | null;
  readonly kind_label: string;
  /** "Gửi mẫu cho KOL" / "Mời KOL": the KOL's handle. */
  readonly kol_handle?: string | null;
  readonly chosen_version: number;
  readonly versions: readonly { readonly version: number; readonly label: string; readonly status: string }[];
  readonly label: string;
  /** Contribution to the plan, per month, P50 of the joint evaluation. */
  readonly contribution_p50: N;
  /** "Bỏ thẻ này thì": the plan without this card, against the plan with it. */
  readonly without: { readonly dprofit_month: N; readonly margin_points: N; readonly aov: N };
  /** The card breaks a floor only when stacked with another card of its product. */
  readonly stack_breach: boolean;
  readonly floor_breach: boolean;
  /** `KH-<yymm>-<seq3>`, once confirmed. */
  readonly plan_code?: string | null;
  readonly sample_cost?: N;
}

export interface StackBreach {
  readonly product_id: string;
  readonly product_name: string;
  readonly cards: readonly { readonly code: string; readonly version: number; readonly label: string }[];
  readonly basket: number;
  readonly buyer_pays: number;
  readonly floor: number;
  readonly shortfall: number;
  /** What each card alone leaves the buyer paying ("Mỗi thẻ riêng lẻ đều đạt"). */
  readonly alone: readonly { readonly code: string; readonly buyer_pays: number }[];
}

export interface PlanAggregate {
  readonly scope: { readonly product_names: readonly string[]; readonly days: number };
  readonly today: PlanSnapshot;
  /** The plan's joint evaluation: low (P10) and high (P90) snapshots. */
  readonly after: { readonly low: PlanSnapshot; readonly high: PlanSnapshot };
  readonly dprofit_certain: N;
  readonly dprofit_month: { readonly p10: N; readonly p50: N; readonly p90: N };
  readonly spend: { readonly per_day_now: N; readonly per_day_after: N; readonly cap: N; readonly over_cap: boolean };
  readonly floor: { readonly ok: boolean; readonly breaches: readonly Breach[] };
}

export interface KolSummary {
  readonly sample_cards: number;
  readonly invite_cards: number;
  readonly sample_cost: number;
  readonly orders: Range<N>;
  readonly profit_after_samples: Range<N>;
  readonly roi: Range<N>;
  readonly payback_orders: number | null;
}

export interface WindowProduct {
  readonly product_id: string;
  readonly product_name: string;
  /** Kinds of the cards of this product's change set. */
  readonly kinds: readonly string[];
  readonly recommended_days: number;
  /** The days in force for this change set (plan default or its own override). */
  readonly days: number;
  readonly override_days: number | null;
  /** Smallest change (%) the window can see for this product. */
  readonly mde_pct: number;
}

export interface PlanWindow {
  /** `auto` = the shortest preset per product whose MDE ≤ 30 %; else one number of days for the plan. */
  readonly mode: "auto" | number;
  readonly presets: readonly number[];
  /** `mde[days][product_id]` in %, for the presets. */
  readonly mde: Readonly<Record<string, Readonly<Record<string, number>>>>;
  readonly products: readonly WindowProduct[];
  readonly min_days: number;
  readonly max_days: number;
}

export interface MeasuringCut {
  readonly product_id: string;
  readonly product_name: string;
  readonly code: string;
  readonly kind_label: string;
  readonly done_days: number;
  readonly total_days: number;
}

export interface Plan {
  readonly id: string | null;
  /** `KH-<yymm>-<seq3>`: issued on confirm, null while a draft. */
  readonly code: string | null;
  readonly status: PlanStatus;
  readonly cards: readonly PlanCardRow[];
  readonly aggregate: PlanAggregate | null;
  readonly stack_breaches: readonly StackBreach[];
  readonly window: PlanWindow | null;
  /** Running measurements that confirming would cut today. */
  readonly cuts: readonly MeasuringCut[];
  readonly kol: KolSummary | null;
  /** Planned execution day (ISO date), once confirmed. */
  readonly execution_date?: string | null;
  readonly acknowledged_breaches?: { readonly at?: string; readonly breaches?: readonly Breach[] } | null;
}

export interface PlanWindowBody {
  readonly days: "auto" | number;
  /** Per change set (product): own days, or null to follow the plan. */
  readonly per_product?: Readonly<Record<string, number | null>>;
}

export interface PlanApi {
  get(): Promise<Plan>;
  add(cardId: string, version: number, acknowledgeBreaches?: boolean): Promise<Plan>;
  remove(cardId: string): Promise<Plan>;
  setVersion(cardId: string, version: number, acknowledgeBreaches?: boolean): Promise<Plan>;
  setWindow(body: PlanWindowBody): Promise<Plan>;
  /** MDE (%) per product for any number of days (`plan.py` computes it for any N). */
  mde(days: number): Promise<Readonly<Record<string, number>>>;
  confirm(acknowledgeBreaches: boolean): Promise<Plan>;
}
