import type { FiveNumbers } from "../shopee-analytics/types";
import type { Breach, N } from "./types";

/**
 * The draft plan "Kế hoạch" (P91 D-6 / D-7 / D-8) exactly as the backend answers it
 * (`services/shopee_recommendations/plans.py`, `plan_aggregate.py`, `change_sets.py`; routes in
 * `api/routes/{demo,ops}_shopee_reco_plan.py`, under the recommendations prefix, seller and Ops alike):
 *   GET  plan · plan/aggregate · plans · plans/{id} · plans/code/{code} · change-sets
 *   POST plan/cards {card_id, chosen_version, acknowledge_breaches}
 *        plan/cards/{id}/remove · /version {version} · /whatif {inputs}
 *        plan/confirm {acknowledge_breaches, planned_date, note} · plan/window {days|null, product_id?}
 *        change-sets/{id}/window {days}
 * Every write answers with the re-aggregated plan ({@link PlanResponse}). A breach that is not
 * acknowledged is refused with 422 `reco_breach_not_acknowledged` and `detail.breaches`.
 * Money is VND per month (the `*_month` fields), `margin_pct` is in percent points.
 */

export type PlanStatus = "draft" | "confirmed" | "executed" | string;

/** Quantiles the backend gives for a month's effect. */
export interface Quantiles {
  readonly p10: N;
  readonly p50: N;
  readonly p90: N;
}

/** `kept_partial` ("Đo được N ngày") or `inconclusive` ("Không kết luận"): what a cut measurement keeps. */
export interface MeasurementCut {
  readonly product_id: string;
  readonly name: string | null;
  readonly change_set: string;
  readonly started_on: string;
  readonly days_measured: number;
  readonly window_days: number;
  readonly state: string;
  readonly label: string;
  readonly days: number;
  readonly low_confidence: boolean;
}

export interface PlanAck {
  readonly by?: unknown;
  readonly at?: string;
  readonly breaches?: readonly Breach[];
}

/** `plan` of the answer; null when the shop has no draft. */
export interface PlanHead {
  readonly id: string;
  readonly status: PlanStatus;
  /** `KH-<yymm>-<seq3>`: issued on confirm, null while a draft. */
  readonly code: string | null;
  readonly as_of: string | null;
  /** The plan's default window; null = automatic per product. */
  readonly window_days: number | null;
  /** Per-product overrides: `{product_id: days}`. */
  readonly product_windows: Readonly<Record<string, number>>;
  /** The one planned execution day (ISO date), once confirmed. */
  readonly planned_date: string | null;
  readonly created_by: unknown;
  readonly created_at: string | null;
  readonly confirmed_by: unknown;
  readonly confirmed_at: string | null;
  readonly executed_at: string | null;
  readonly acknowledged_breaches: PlanAck | null;
  /** The running measurements that confirming (or the confirmation made) cut. */
  readonly measurement_cut: readonly MeasurementCut[];
  /** P97 D85.4: the frozen base of a draft plan (absent on plans from before the base existed). */
  readonly base?: PlanBase | null;
}

/** The day a draft plan's numbers are on; only "Cập nhật số" moves it. */
export interface PlanBase {
  /** P99b: a draft is recomputed live on every read; there is no frozen base and no "Cập nhật số". */
  readonly live?: boolean;
  readonly label?: string;
  readonly version?: number;
  readonly as_of: string;
  readonly window?: unknown;
  readonly newest_day: string | null;
  readonly newer_available: boolean;
  readonly horizon_from?: string | null;
  readonly refreshed_at?: string | null;
  /** Vietnamese sentence the screen shows as is. */
  readonly note: string;
}

export interface PlanVersion {
  readonly version: number;
  readonly code: string | null;
  readonly label: string | null;
  /** `ok` | `floor_breach` | `spend_breach` | `refused`. */
  readonly status: string;
  readonly ranked: boolean;
  readonly inputs: Readonly<Record<string, unknown>> | null;
  readonly floor_ok: boolean | null;
  readonly dprofit_month_p50: N;
  readonly dgmv_month_p50: N;
}

/** `dprofit` / `dgmv` of one evaluation or of the plan with and without a card. */
export interface Brief {
  /** `certain` is null on the P99 results path ("—", never 0). */
  readonly dprofit: { readonly certain?: N } & Quantiles;
  readonly dgmv: { readonly certain?: N; readonly p50: N };
  readonly dorders_p50: N;
  readonly cost_month: number;
  readonly floor_ok: boolean;
}

/** P99: a card's (or product's) 30-day funnel base; every key may be null. */
export interface PlanFunnel {
  readonly gmv_30d?: N;
  readonly orders_30d?: N;
  readonly profit_30d?: N;
  readonly views_30d?: N;
  readonly clicks_30d?: N;
  readonly aov?: N;
  readonly margin_pct?: N;
  readonly ctr?: N;
  readonly ctor?: N;
  readonly label?: string;
}

/** P99b: the dates a card's effect is measured on. */
export interface DateSpan {
  readonly from: string;
  readonly to: string;
  readonly days: number;
}

/** P99: what a card contributes to the sums: its own base, Δ and cost. */
export interface PlanCardResult {
  readonly estimable: boolean;
  readonly counted: boolean;
  readonly message: string | null;
  readonly reason: string | null;
  readonly delta: Readonly<Record<"p10" | "p50" | "p90", { readonly dgmv: N; readonly dorders: N; readonly dprofit: N }>> | null;
  /** Alias of `cost_horizon` (kept by the API; the screen reads `cost_horizon`). */
  readonly cost_month?: N;
  /** P99b: the plan's horizon ("30 ngày tới"). */
  readonly horizon?: DateSpan | null;
  readonly own_dates?: DateSpan | null;
  readonly own_days?: N;
  readonly dated?: boolean;
  readonly counted_dates?: DateSpan | null;
  readonly counted_days?: N;
  readonly outside_horizon?: boolean;
  /** Cost over the card's own dates / over the horizon; null = chưa biết chi phí. */
  readonly cost_total: N;
  readonly cost_horizon?: N;
  readonly cost_known?: boolean;
  readonly cost_note?: string | null;
  readonly partial_note?: string | null;
  readonly own?: {
    readonly dates?: DateSpan | null;
    readonly days?: N;
    readonly delta?: Readonly<Record<"p10" | "p50" | "p90", { readonly dgmv: N; readonly dorders: N; readonly dprofit: N }>> | null;
    readonly cost_total?: N;
  } | null;
  readonly break_even_orders: N;
  readonly days: N;
  /** Renamed in P99b: "duration" | "first_30_days". */
  readonly result_horizon?: string | null;
  readonly before: PlanFunnel | null;
  readonly after: PlanFunnel | null;
  readonly notes: readonly string[];
}

/** One card of `aggregate.cards`: its evaluation as part of the plan. */
export interface PlanEvaluation {
  readonly card_id: string;
  readonly code: string;
  readonly title: string;
  readonly family: string;
  readonly change_kind: string;
  readonly product_id: string | null;
  readonly version: number;
  readonly version_label: string | null;
  readonly inputs: Readonly<Record<string, unknown>>;
  readonly what_if: Readonly<Record<string, unknown>>;
  /** True when the card is evaluated on the same orders as another card of its product. */
  readonly in_joint_layer: boolean;
  readonly alone: Brief;
  /** What the plan gains from this card: plan minus plan-without-it. */
  readonly contribution: { readonly dprofit_certain?: N; readonly dprofit_p50: N; readonly dgmv_p50: N; readonly cost_month: N };
  /** The plan without this card ("Bỏ thẻ này thì"); null when it is the only card. */
  readonly without: (Brief & { readonly delta: { readonly dprofit_p50: N; readonly dgmv_p50: N; readonly cost_month: N } }) | null;
  readonly floor_ok: boolean;
  readonly breaches: readonly PlanBreach[];
  /** P99: the card's own base, Δ and cost (absent on an older server). */
  readonly result?: PlanCardResult;
}

/** A plan-level breach: a floor (`sku`, `kind`, `floor`, `min_unit_price`) or the spend cap. */
export interface PlanBreach extends Breach {
  readonly card_id?: string;
  /** Cards whose own evaluation breaches this SKU (empty when only the stack does). */
  readonly card_ids?: readonly string[];
  readonly only_when_stacked?: boolean;
  readonly stacked?: boolean;
  readonly spend_per_day_after?: N;
  readonly over_by_per_day?: N;
}

export interface PlanCard {
  readonly card_id: string;
  readonly code: string;
  readonly plan_code: string | null;
  readonly status: string;
  readonly product_id: string | null;
  readonly title: string | null;
  readonly family: string | null;
  readonly change_kind: string | null;
  readonly chosen_version: number;
  readonly chosen_version_code: string | null;
  readonly versions: readonly PlanVersion[];
  /** The what-if inputs the seller moved on this card inside the plan. */
  readonly what_if: Readonly<Record<string, unknown>>;
  readonly added_at: string | null;
  readonly added_by: unknown;
  readonly acknowledged_breaches: PlanAck | null;
  /** P97 D85.14: the groups this card has a version in (`letter` + version). */
  readonly groups?: readonly { readonly letter: string; readonly version: number }[];
  /** P97 D85.13: how many targets a many-target card applies to (0 = one product). */
  readonly n_targets?: number;
  /** Null while the plan could not evaluate the card. */
  readonly evaluation: PlanEvaluation | null;
  /** P99b: on `ads_new_campaign` cards, what the hand-made campaign actually did. */
  readonly ads_readback?: AdsReadback | null;
}

export interface AdsReadbackActual {
  readonly spend: N;
  readonly gmv: N;
  readonly orders: N;
  readonly roas: N;
  readonly basis?: string | null;
  readonly from?: string | null;
  readonly to?: string | null;
  readonly days_covered?: N;
  readonly days_expected?: N;
  readonly reasons?: Readonly<Partial<Record<"spend" | "gmv" | "orders" | "roas" | "coverage", string>>>;
}

export interface AdsReadback {
  readonly state: "matched" | "not_found" | "ambiguous" | (string & {});
  readonly label?: string | null;
  readonly reason?: string | null;
  readonly reason_text?: string | null;
  readonly matched_by?: string | null;
  readonly campaign?: { readonly name?: string | null; readonly segment?: string | null; readonly first_day?: string | null; readonly item_ids?: readonly string[] } | null;
  readonly candidates?: readonly { readonly name?: string | null; readonly segment?: string | null; readonly first_day?: string | null; readonly item_ids?: readonly string[] }[];
  readonly started_before_card?: boolean | null;
  readonly actual?: AdsReadbackActual | null;
}

export interface WindowPreset {
  readonly days: number;
  readonly mde: N;
  /** Smallest change (%) the window can see. */
  readonly mde_pct: N;
  readonly ok: boolean;
  readonly hard: boolean;
  readonly label: string;
  readonly recommended: boolean;
}

export interface WindowOptions {
  readonly metric: string;
  readonly min_days: number;
  readonly max_days: number;
  readonly presets: readonly WindowPreset[];
  readonly recommended_days: number | null;
  readonly default_days: number;
}

export interface ProductBlock {
  readonly product_id: string;
  readonly name: string | null;
  readonly cards: readonly string[];
  readonly codes: readonly string[];
  readonly joint: Brief;
  /** P99: the product's own funnel today / after (absent or null when not computable). */
  readonly today?: PlanFunnel | null;
  readonly after?: PlanFunnel | null;
  readonly predicted_rel_gmv: Readonly<Record<string, N>>;
  readonly base_gmv_30d: number;
  readonly orders_per_day: N;
  readonly window: WindowOptions;
  /** P92 B-10: the product's cards as ordered steps (price, giảm giá, voucher, combo, ads). */
  readonly steps?: ProductSteps;
}

export type StepKey = "price" | "giam_gia" | "voucher" | "combo" | "ads" | (string & {});

/** One step of a product's draft: evaluated on top of the previous steps. `null` = not computable. */
export interface PlanStep {
  readonly index: number;
  readonly step: StepKey;
  readonly step_label: string;
  readonly card_id: string;
  readonly code: string | null;
  readonly title: string | null;
  readonly change_kind: string;
  readonly version_label?: string | null;
  readonly margin_pct_before: N;
  readonly margin_pct_after: N;
  readonly dprofit_step_p50: N;
  readonly dprofit_total_p50: N;
  readonly dprofit_total_certain?: N;
  readonly dgmv_total_p50: N;
  readonly cost_month_total: N;
  readonly floor_ok: boolean;
}

export interface ProductSteps {
  readonly order: readonly StepKey[];
  readonly custom_order: boolean;
  readonly items: readonly PlanStep[];
  readonly total: {
    readonly margin_pct_before: N;
    readonly margin_pct_after: N;
    readonly dprofit_p50: N;
    readonly dprofit_certain?: N;
    readonly dgmv_p50: N;
  };
}

export interface StepsSummary {
  readonly shop: {
    readonly dprofit_p50: N;
    readonly dprofit_certain?: N;
    readonly margin_pct_after: N;
    readonly products: number;
  };
}

export interface StackedProduct {
  readonly product_id: string;
  readonly cards: readonly string[];
  readonly codes: readonly string[];
  readonly count: number;
  readonly stacked_on_same_orders: boolean;
}

export interface PlanCost {
  readonly per_day_before: number;
  readonly per_day_after: number;
  readonly delta_per_day: number;
  readonly per_month_after: number;
  /** P99b: the plan's cost over the horizon (not "per month"). */
  readonly delta_per_month: number;
  readonly cap_per_day: N;
  readonly over_cap: boolean;
  readonly over_by_per_day: number;
  readonly label: string;
  readonly horizon?: DateSpan | null;
  readonly horizon_spend_before?: N;
  readonly horizon_spend_delta?: N;
  readonly horizon_spend_after?: N;
  readonly horizon_cap?: N;
  readonly over_by_horizon?: N;
  readonly cost_unknown_cards?: readonly string[];
  readonly cost_complete?: boolean;
  readonly cost_note?: string | null;
}

export interface PlanToday {
  readonly as_of: string;
  readonly gmv_30d: number;
  readonly orders_30d: number;
  readonly aov: N;
  /** Percent points (18.4 = 18,4%). */
  readonly margin_pct: N;
}

export interface PlanAfter {
  readonly gmv_30d: number;
  readonly orders_30d: number;
  readonly aov: N;
  readonly margin_pct: N;
  readonly label: string;
}

/** P99b: the window has no stored daily rows: the aggregate is only this state, no figures. */
export interface DataMissing {
  readonly code: string;
  readonly message: string;
  readonly window?: { readonly from: string; readonly to: string } | null;
  readonly missing_days?: number | readonly string[] | null;
  readonly first_missing?: string | null;
}

/** `aggregate` of the answer; with no card it is only `as_of`, `n_cards: 0`, `today`, `cards: []`. */
export interface PlanAggregate {
  readonly as_of?: string;
  readonly n_cards: number;
  /** P99b: "30 ngày tới: dd/mm – dd/mm". */
  readonly horizon?: (DateSpan & { readonly label?: string }) | null;
  readonly live?: boolean;
  readonly data_missing?: DataMissing | null;
  readonly empty?: boolean;
  readonly empty_note?: string | null;
  readonly outside_horizon_cards?: readonly string[];
  readonly cost_unknown_cards?: readonly string[];
  readonly totals_partial?: boolean;
  readonly totals_note?: string | null;
  readonly result_basis?: string | null;
  readonly today: PlanToday | null;
  readonly after?: PlanAfter | null;
  readonly deltas_p50?: { readonly gmv: N; readonly orders: N; readonly aov: N; readonly bien: N } | null;
  readonly five_numbers?: FiveNumbers | null;
  readonly dprofit_month?: { readonly certain?: N; readonly predicted: Quantiles; readonly total: Quantiles };
  readonly dgmv_month?: { readonly certain?: N; readonly total: Quantiles };
  readonly dorders_month?: Quantiles;
  readonly cost?: PlanCost | null;
  readonly floor?: { readonly ok: boolean; readonly breaches: readonly PlanBreach[] };
  readonly breaches?: readonly PlanBreach[];
  readonly stacked_products?: readonly StackedProduct[];
  readonly cards: readonly PlanEvaluation[];
  readonly products?: readonly ProductBlock[];
  readonly steps_summary?: StepsSummary;
  readonly shop_wide?: { readonly cards: readonly string[]; readonly codes: readonly string[]; readonly joint: Brief } | null;
  readonly joint_cards?: readonly string[];
  readonly added_cards?: readonly string[];
  readonly profit_unknown_cards?: readonly string[];
  readonly unavailable_cards: readonly string[];
  readonly notes?: readonly string[];
  readonly range_method: string;
  readonly range_note?: string;
}

/** P97 D85.14: one version of one card inside a group. */
export interface PlanGroupMember {
  readonly card_id: string;
  readonly plan_card_id: string;
  readonly entry_id: string;
  readonly code: string | null;
  readonly version: number;
  readonly version_code: string | null;
  readonly version_label: string | null;
  readonly title: string | null;
  readonly change_kind: string | null;
  readonly family: string | null;
  readonly product_id: string | null;
  readonly n_targets: number;
}

/** "Nhóm A, B ...": options that run together with ONE period (at least 3 days); the aggregate is the plan math over its members. */
export interface PlanGroup {
  readonly id: string;
  readonly letter: string;
  readonly name: string;
  readonly position: number;
  /** `<card code>-G<letter>`. */
  readonly code: string | null;
  readonly status: "draft" | "approved" | string;
  readonly days: number;
  readonly start: string;
  readonly end: string;
  readonly start_fixed: boolean;
  readonly min_days: number;
  readonly members: readonly PlanGroupMember[];
  readonly aggregate: PlanAggregate | null;
}

export interface PlanNotice {
  readonly type: "moved_to_group" | string;
  readonly group?: string;
  readonly message: string;
}

export interface WindowProductRow {
  readonly product_id: string;
  readonly name: string | null;
  /** The days in force for this product's change set. */
  readonly days: number;
  /** `custom` (the product's own) | `plan` (the plan's default) | `auto`. */
  readonly source: "custom" | "plan" | "auto" | string;
  readonly recommended_days: number | null;
  readonly options: WindowOptions;
  readonly orders_per_day: N;
  readonly hard: boolean;
}

/** `windows` of the answer; null for an empty plan. */
export interface PlanWindows {
  readonly plan_default_days: number | null;
  readonly plan_default_source: "plan" | "auto" | string;
  readonly min_days: number;
  readonly max_days: number;
  readonly presets: readonly number[];
  readonly per_product: readonly WindowProductRow[];
}

/** A change set: the unit of measurement (one product, one execution day). */
export interface ChangeSet {
  readonly id: string;
  readonly scope: string;
  readonly product_id: string | null;
  readonly plan_id: string | null;
  readonly executed_on: string;
  readonly started_at: string;
  readonly card_ids: readonly string[];
  readonly n_cards: number;
  readonly window_days: number;
  readonly window_source: string;
  readonly until: string;
  readonly days_left: number | null;
  readonly status: "measuring" | "done" | "cut" | string;
  readonly with_shop_wide: boolean;
  readonly with_shop_wide_label: string | null;
  readonly predicted: unknown;
  readonly result: unknown;
  readonly cut_at: string | null;
  readonly cut_days: number | null;
}

/** The answer of `GET plan` and of every plan write. */
/** One scope of Kế hoạch's month figures (`month_plan.month_plans`): goal = baseline + uplift. */
export interface PlanMonthTotals {
  readonly scope: "running" | "running+draft";
  readonly month: string;
  readonly day: number;
  readonly days_in_month: number;
  readonly cards: number;
  readonly baseline_gmv: number | null;
  readonly baseline_profit: number | null;
  readonly uplift_gmv: number | null;
  readonly uplift_profit: number | null;
  readonly goal_gmv: number | null;
  readonly goal_profit: number | null;
  readonly mtd_gmv: number | null;
  readonly mtd_profit: number | null;
}

export interface PlanResponse {
  readonly plan: PlanHead | null;
  /** The two totals of the month: "Đang chạy" (executed plans) and "Nếu áp dụng nháp" (+ the draft). */
  readonly month?: { readonly running: PlanMonthTotals; readonly with_draft: PlanMonthTotals } | null;
  readonly cards: readonly PlanCard[];
  readonly aggregate: PlanAggregate | null;
  /** P97 D85.14: the groups of the plan; `aggregate` is then the cards that are in no group. */
  readonly groups?: readonly PlanGroup[];
  /** Said when an option moved to a later group because an exclusive field was taken. */
  readonly notice?: PlanNotice | null;
  readonly windows: PlanWindows | null;
  readonly change_sets: readonly ChangeSet[];
  /** Only on the answer of `plan/confirm`: the same list as `plan.measurement_cut`. */
  readonly measurement_cut?: readonly MeasurementCut[];
}

export interface ConfirmBody {
  readonly acknowledgeBreaches: boolean;
  /** ISO date, today or later; the backend defaults to today. */
  readonly plannedDate?: string;
  readonly note?: string;
}

export interface GroupMemberRef {
  readonly cardId: string;
  readonly version: number;
}

export interface PlanApi {
  get(): Promise<PlanResponse>;
  /** "Chạy cùng nhau" for cards of the plan: these versions become one group with one period (days >= 3). */
  createGroup?(members: readonly GroupMemberRef[], opts: { readonly days: number; readonly start?: string | null; readonly acknowledgeBreaches?: boolean }): Promise<PlanResponse>;
  setGroupPeriod?(groupId: string, patch: { readonly days?: number; readonly start?: string | null; readonly clearStart?: boolean }): Promise<PlanResponse>;
  removeGroupMember?(groupId: string, member: GroupMemberRef): Promise<PlanResponse>;
  cancelGroup?(groupId: string): Promise<PlanResponse>;
  /** P100: Kế hoạch of a month ("YYYY-MM") as an Excel file; absent = no download. */
  exportKeHoach?(month: string | null): Promise<Blob>;
  /** `version` null = the version and what-if the card had when it was last removed from the plan (else V1). */
  add(cardId: string, version: number | null, acknowledgeBreaches?: boolean): Promise<PlanResponse>;
  remove(cardId: string): Promise<PlanResponse>;
  /** P92 B-10: move a planned card to a 1-based position among the plan's cards (re-orders its product's steps). */
  move?(cardId: string, position: number): Promise<PlanResponse>;
  setVersion(cardId: string, version: number): Promise<PlanResponse>;
  /** What-if inputs of one planned card (the plan is re-aggregated on them). */
  whatIf(cardId: string, inputs: Readonly<Record<string, unknown>>): Promise<PlanResponse>;
  /** The measurement window: `days` for the whole plan (null = automatic per product), or for one product. */
  setWindow(days: number | null, productId?: string): Promise<PlanResponse>;
  setChangeSetWindow(changeSetId: string, days: number): Promise<ChangeSet>;
  /** "Cập nhật số": move the draft plan's base to the newest complete day. */
  refreshBase?(): Promise<PlanResponse>;
  confirm(body: ConfirmBody): Promise<PlanResponse>;
  changeSets(query?: { readonly productId?: string; readonly status?: "measuring" | "done" | "cut" }): Promise<readonly ChangeSet[]>;
}
