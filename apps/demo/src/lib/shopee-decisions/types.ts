import type { FiveNumbers } from "../shopee-analytics/types";

/**
 * Payloads of the Shopee recommendation-card API (`/v1/demo/shopee/recommendations` for the seller,
 * `/v1/ops/shops/{id}/shopee/recommendations` for Juli Ops; `services/shopee_recommendations`
 * `cards.py` / `service.py` / `sheet.py` / `mega.py`). Money is a JSON number in VND; `null` is "not
 * known" and prints "—", never 0. Fields the seller view hides (model version, rank internals) are
 * optional here because Ops sees them.
 */

export type N = number | null;

export type Family = "ads" | "promotion" | "voucher" | "sale" | "combo" | "affiliate" | "mega_sale";

/** Card status (`shop_proposals.status`; `draft` exists for Ops only). */
export type CardStatus =
  | "draft"
  | "sent"
  | "approved"
  | "changes_requested"
  | "rejected"
  | "executed"
  | "expired"
  | "withdrawn"
  | "superseded"
  | string;

export interface CardMetric {
  readonly key: string;
  readonly critical_id: string | null;
  readonly critical_kpi: string | null;
  readonly flow: string | null;
  readonly at_stake_per_day: N;
}

export interface CardScope {
  readonly level: string;
  readonly product_ids: readonly string[];
  readonly sku_ids: readonly string[];
  readonly campaign_key: string | null;
}

export interface Quantiles {
  readonly p10: N;
  readonly p50: N;
  readonly p90: N;
}

/** Where a listed card stands in the Connector's read-back of "Đã làm". */
export type VerificationState = "pending" | "verified" | "mismatch" | "not_seen";

export interface CardSummary {
  readonly id: string;
  readonly status: CardStatus;
  readonly cycle?: number;
  readonly family: Family;
  readonly family_label: string;
  readonly change_kind: string;
  readonly title: string;
  readonly reason: string | null;
  /** The critical metric the card answers (`wiring_key`): aov, ctor, bien, roas, lien_ket, sale… */
  readonly section: string | null;
  readonly metric: CardMetric;
  readonly scope: CardScope;
  readonly rank: { readonly position?: number | null; readonly explore?: boolean } | null;
  readonly certain_summary: { readonly dprofit_month: N; readonly dgmv_month: N };
  readonly predicted_summary: {
    readonly dgmv_month: Quantiles;
    readonly dprofit_month: Quantiles;
    readonly label: string;
    readonly effect_days: number;
  };
  readonly floor_ok: boolean;
  readonly plan: string;
  readonly stale: boolean;
  readonly bundle: boolean;
  readonly sent_at: string | null;
  /** The "đáng thử" slot (ranking contract 11), when the API flags it. */
  readonly worth_trying?: boolean;
  /** Optional read-back summary of an executed card. */
  readonly verification?: { readonly state: VerificationState } | null;
}

export interface CardList {
  readonly platform: "shopee";
  readonly xep_theo: string;
  readonly cards: readonly CardSummary[];
  readonly counts: {
    readonly family: Readonly<Record<string, number>>;
    readonly section: Readonly<Record<string, number>>;
    readonly total: number;
  };
}

export interface SliderRow {
  readonly key: string;
  readonly label: string;
  readonly unit: "vnd" | "pct" | "count" | "days" | "roas" | string;
  readonly min: number;
  readonly max: number;
  readonly step: number;
  readonly default: N;
  readonly default_source?: string;
}

export interface FloorBreach {
  readonly sku: string;
  /** "operating" (giá sàn vận hành) | "absolute" (giá sàn tuyệt đối). */
  readonly kind: string;
  readonly floor: N;
  readonly min_unit_price: N;
  readonly lines?: number;
  readonly stacked?: boolean;
}

export interface SpendCheck {
  readonly shop_chi_per_day_now: N;
  readonly card_dchi_per_day: N;
  readonly shop_chi_per_day_after: N;
  readonly cap: N;
  readonly over_cap: boolean | null;
  readonly basis?: string;
}

export interface MoneyAt {
  readonly dgmv: N;
  readonly dorders: N;
  readonly dprofit: N;
}

export interface MoneyPerMonth {
  readonly days: number;
  readonly certain: { readonly dgmv: N; readonly dprofit: N; readonly dchi: N };
  readonly predicted: { readonly p10: MoneyAt; readonly p50: MoneyAt; readonly p90: MoneyAt };
  readonly total: { readonly p10: MoneyAt; readonly p50: MoneyAt; readonly p90: MoneyAt };
}

export interface GroupJson {
  readonly orders: number;
  readonly profit_per_order: N;
  readonly contribution_per_order: N;
}

/** `certain` of a voucher card (`evaluate.eval_voucher`); other families carry their own keys. */
export interface Certain {
  readonly label: string;
  readonly kind?: string;
  readonly qualifying_orders?: number;
  readonly total_orders?: number;
  readonly days?: number;
  readonly usage_limit?: N;
  readonly per_user_limit?: N;
  readonly per_user_limit_status?: string | null;
  readonly voucher_cost_scenario?: N;
  readonly voucher_cost_baseline?: N;
  readonly extra_cost?: N;
  readonly voucher_spend_per_day?: N;
  readonly voucher_spend_check?: { readonly per_day: N; readonly cap: N; readonly over_cap: boolean } | null;
  readonly organic?: GroupJson;
  readonly ad_attributed?: GroupJson;
  readonly ad_margin_below_target?: boolean;
  readonly break_even_extra_orders?: N;
  readonly break_even_reason?: string | null;
  readonly extra_orders_label?: string;
  readonly predicted_net?: {
    readonly net_profit_low: N;
    readonly net_profit_high: N;
    readonly extra_revenue_per_extra_spend_low: N;
    readonly extra_revenue_per_extra_spend_high: N;
    readonly source?: string;
  };
  // mega_sale
  readonly window?: { readonly start: string; readonly end: string; readonly days: number };
  readonly orders_in_window_expected?: N;
  readonly total_discount?: N;
  readonly by_lever?: readonly { readonly lever: string; readonly lines: number; readonly discount: N }[];
  readonly skus?: readonly MegaSkuRow[];
  readonly no_double_counting?: string;
  readonly spend?: {
    readonly cap_per_day: N;
    readonly shop_cap_per_day: N;
    readonly mega_chi_per_day: N;
    readonly baseline_chi_per_day: N;
    readonly over_budget: boolean | null;
    readonly over_shop_cap: boolean | null;
  };
  readonly [extra: string]: unknown;
}

export interface MegaSkuRow {
  readonly sku: string;
  readonly worst_unit_net_revenue: N;
  readonly floor: N;
  readonly below_floor: boolean;
}

export interface ExecutionStep {
  readonly order: number;
  readonly field: string;
  readonly before: string | number | null;
  readonly after: string | number | null;
  readonly unit?: string | null;
  /** The exact text to paste (null: nothing to paste). */
  readonly copy: string | null;
  readonly child_card_id?: string | null;
  readonly page?: SheetPage | null;
  readonly starts?: string | null;
}

export interface SheetPage {
  readonly label: string;
  readonly path: string | null;
  readonly verified: boolean;
  readonly deep_link: string | null;
  readonly button: string;
}

export interface ExecutionSheet {
  readonly page: SheetPage;
  readonly steps: readonly ExecutionStep[];
  readonly time_window: { readonly start?: string; readonly days?: N };
  readonly changes: readonly { readonly change_kind: string; readonly target: Readonly<Record<string, unknown>>; readonly expected: Readonly<Record<string, unknown>> }[];
  readonly save_hint: string;
  readonly revert_steps: readonly ExecutionStep[];
  readonly readback: { readonly kinds: readonly string[]; readonly deadline_hours: number; readonly note: string };
}

export interface MeasurementPlan {
  readonly metric: string;
  readonly planned_days: number | null;
  readonly label: string;
  readonly expected_sample?: N;
  readonly required_sample?: N;
  readonly pooled_only?: boolean;
  readonly clock_starts?: string;
}

export interface MegaChild {
  readonly child_id: string;
  readonly source_card_id: string | null;
  readonly change_kind: string;
  readonly family: Family | string;
  readonly label: string;
  readonly items: readonly string[];
  readonly campaign_key: string | null;
  readonly inputs: Readonly<Record<string, unknown>>;
  readonly summary: Readonly<Record<string, unknown>> | null;
  readonly page: SheetPage | null;
  readonly starts: string;
}

export interface ScheduleDay {
  readonly date: string;
  readonly events: readonly { readonly child_id: string; readonly kind: string; readonly action: "bat" | "tat" | string; readonly at: string }[];
}

export interface Card {
  readonly id?: string;
  readonly family: Family;
  readonly family_label: string;
  readonly change_kind: string;
  readonly title: string;
  readonly reason: string | null;
  readonly as_of: string;
  readonly window: { readonly from: string; readonly to: string; readonly days: number };
  readonly order_basis: { readonly key: string; readonly label: string };
  readonly metric: CardMetric;
  readonly scope: CardScope;
  readonly change: {
    readonly change_kind: string;
    readonly target: Readonly<Record<string, unknown>>;
    readonly before: Readonly<Record<string, unknown>>;
    readonly after: Readonly<Record<string, unknown>>;
  };
  readonly inputs: Readonly<Record<string, unknown>>;
  readonly whatif: { readonly sliders: readonly SliderRow[]; readonly children_editable?: boolean };
  readonly certain: Certain;
  readonly five_numbers: FiveNumbers;
  readonly floor: { readonly breaches: readonly FloorBreach[]; readonly unknown_skus: readonly string[]; readonly ok: boolean };
  readonly spend: SpendCheck | null;
  readonly predicted: {
    readonly label: string;
    readonly money_per_month: MoneyPerMonth;
    readonly lift?: { readonly metric?: string; readonly lift?: Quantiles };
    readonly base?: string;
  };
  readonly measurement_plan: MeasurementPlan;
  readonly execution_sheet: ExecutionSheet;
  readonly notes?: readonly string[];
  readonly bundle: boolean;
  // mega_sale only
  readonly children?: readonly MegaChild[];
  readonly schedule?: readonly ScheduleDay[];
  readonly mega_window?: { readonly start: string; readonly end: string; readonly days: number };
}

export interface JourneyEvent {
  readonly event: string;
  readonly at: string;
  readonly reason_code: string | null;
  /** Read-back / measurement payloads, when the API sends them (see {@link readbackOf}). */
  readonly payload?: Readonly<Record<string, unknown>> | null;
}

export interface CardDetail extends CardSummary {
  readonly card: Card;
  readonly journey: readonly JourneyEvent[];
  /**
   * What the seller approved when they moved the sliders. `execution_sheet` is the sheet of those final
   * values; when the API does not send it the screen recomputes it from `inputs`.
   */
  readonly approved_with?: { readonly inputs: Readonly<Record<string, unknown>>; readonly execution_sheet?: ExecutionSheet };
}

export interface DecideResult {
  readonly id: string;
  readonly status: CardStatus;
  readonly approval_id: string;
  readonly reason_code?: string;
}

export interface ExecutedResult {
  readonly id: string;
  readonly status: CardStatus;
  readonly execution_id: string;
  readonly events: number;
}

// ── Ops-only ────────────────────────────────────────────────────────────────

export interface GenerateReport {
  readonly generated: number;
  readonly persisted: number;
  readonly by_family: Readonly<Record<string, number>>;
  readonly card_ids: readonly string[];
  readonly [extra: string]: unknown;
}

export interface LearningOverview {
  readonly calibration: unknown;
  readonly acceptance: unknown;
  readonly sim: unknown;
  readonly note?: string;
}
