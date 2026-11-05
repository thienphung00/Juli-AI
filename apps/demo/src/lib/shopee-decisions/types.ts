import type { KolBlock } from "../shopee-kol/types";
import type { FiveNumbers } from "../shopee-analytics/types";

/**
 * Payloads of the Shopee recommendation-card API (`/v1/demo/shopee/recommendations` for the seller,
 * `/v1/ops/shops/{id}/shopee/recommendations` for Juli Ops; `services/shopee_recommendations`
 * `cards.py` / `service.py` / `sheet.py` / `mega.py`). Money is a JSON number in VND; `null` is "not
 * known" and prints "—", never 0. Fields the seller view hides (model version, rank internals) are
 * optional here because Ops sees them.
 */

export type N = number | null;

export type Family = "ads" | "promotion" | "voucher" | "sale" | "combo" | "affiliate" | "listing" | "mega_sale";

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

/** P91 D-2: `ok` | `floor_breach` | `spend_breach` | `refused` (a refused version is shown, never approvable). */
export type VersionStatus = "ok" | "floor_breach" | "spend_breach" | "refused" | string;

/** A version as the list and the by-code read summarise it (`service._version_brief`). */
export interface VersionBrief {
  readonly version: number;
  readonly code: string | null;
  readonly label: string | null;
  readonly status: VersionStatus;
  readonly ranked: boolean;
  readonly inputs?: Readonly<Record<string, unknown>> | null;
  readonly floor_ok?: boolean | null;
  readonly dprofit_month_p50?: N;
  readonly dgmv_month_p50?: N;
}

/** `{until: "YYYY-MM-DD", change_set}` of a product whose last change is still being measured (P91 D-1 / D-7). */
export interface ProductMeasuring {
  readonly until: string;
  readonly change_set?: unknown;
}

export interface CardSummary {
  readonly id: string;
  /** P91 D-5: `JC-<yymm>-<seq4>`; absent on a card from before migration 116. */
  readonly code?: string | null;
  readonly product_id?: string | null;
  /** 1 = the card Quyết định shows for its product, 2.. wait behind it. */
  readonly product_queue?: number | null;
  readonly product_measuring?: ProductMeasuring | null;
  readonly versions?: readonly VersionBrief[];
  /** "manual" for a card made by hand (Tự tạo phương án); the engine's cards carry none. */
  readonly origin?: string | null;
  readonly created_at?: string | null;
  /** P91 D-6 (assumed, wave 1b): the plan the card was confirmed in. */
  readonly plan_code?: string | null;
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
  /** Why it is stale (`engine_version_changed` | `inputs_changed` | …): the card shows "đang cập nhật". */
  readonly stale_reason?: string | null;
  /** When the numbers were computed ("Cập nhật lúc …"). */
  readonly computed_at?: string | null;
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
  readonly queue?: string;
  readonly cards: readonly CardSummary[];
  readonly counts: {
    readonly family: Readonly<Record<string, number>>;
    readonly section: Readonly<Record<string, number>>;
    readonly total: number;
    readonly queued_behind?: number;
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

type Quantile3<T> = { readonly p10: T; readonly p50: T; readonly p90: T };

/** The same money per DAY (flows) and over the change's own days (`period`); the seller reads these, not a month. */
export interface MoneyBlock {
  readonly days?: number;
  readonly certain: { readonly dgmv: N; readonly dprofit: N; readonly dchi: N };
  readonly total: Quantile3<MoneyAt>;
}

export interface MoneyPerMonth {
  readonly days: number;
  readonly certain: { readonly dgmv: N; readonly dprofit: N; readonly dchi: N };
  readonly predicted: { readonly p10: MoneyAt; readonly p50: MoneyAt; readonly p90: MoneyAt };
  readonly total: { readonly p10: MoneyAt; readonly p50: MoneyAt; readonly p90: MoneyAt };
  /** Over the change's own days (not capped at a month). Absent on cards stored before the units change. */
  readonly period?: MoneyBlock & { readonly days: number };
  readonly per_day?: MoneyBlock;
  /** Unit economics: per order that uses the change (`basis`), Δ profit and cost. */
  readonly per_order?: { readonly basis: "order" | "voucher_use"; readonly orders_in_period: number; readonly certain: { readonly dprofit: N; readonly cost: N }; readonly total: Quantile3<{ readonly dprofit: N }> };
  /** Orders the model expects (`changes` false: an AOV lever, orders stay as they were). */
  readonly orders?: { readonly base_per_day: number; readonly total: Quantile3<{ readonly per_day: N; readonly period: N; readonly changes: boolean }> };
  readonly aov?: { readonly base: N; readonly certain: N; readonly total: Quantile3<N> };
}

export interface VoucherDetail {
  readonly days: number;
  readonly usage: { readonly expected_uses: N; readonly used: N; readonly limit: N; readonly capped: boolean; readonly headroom: N };
  readonly per_user: { readonly limit: N; readonly status: string | null; readonly enforced: boolean };
  readonly max_discount: { readonly value: N; readonly applies: boolean; readonly pct_voucher: boolean; readonly binding_orders: number; readonly qualifying_orders: number; readonly binding_share: N };
  readonly min_spend: { readonly value: N; readonly qualifying_orders: number; readonly total_orders: number };
  readonly cost_per_used_order: N;
  readonly profit_per_order_after: N;
}

export interface Freshness {
  readonly computed_at: string;
  readonly engine_version: string;
  readonly inputs_fingerprint: string;
  readonly as_of: string;
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
  readonly voucher_detail?: VoucherDetail;
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
  /** P91 D-13: this one product's edit page (listing kinds); its address shape is not recon-verified yet. */
  readonly item_deep_link?: string | null;
  readonly item_link_verified?: boolean;
}

export interface ExecutionSheet {
  readonly page: SheetPage;
  readonly steps: readonly ExecutionStep[];
  readonly time_window: { readonly start?: string; readonly days?: N };
  readonly changes: readonly { readonly change_kind: string; readonly target: Readonly<Record<string, unknown>>; readonly expected: Readonly<Record<string, unknown>> }[];
  readonly save_hint: string;
  /** P91 D-13: changes that must run before this one ("chỉ sau khi CB3 chạy"), and a cover image to download. */
  readonly dependencies?: readonly { readonly ref: string; readonly code?: string | null; readonly text: string }[];
  readonly downloads?: readonly { readonly label: string; readonly ref: string; readonly url: string | null }[];
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

/** One evaluation of the change (P91 D-2): the same fields as a card, plus the version header. */
export interface CardVersion {
  readonly version: number;
  readonly code: string | null;
  readonly label: string | null;
  readonly status: VersionStatus;
  readonly default?: boolean;
  readonly ranked: boolean;
  readonly refusal: string | null;
  readonly inputs: Readonly<Record<string, unknown>>;
  // the evaluation fields; absent on a refused version
  readonly reason?: string | null;
  readonly change?: Card["change"];
  readonly whatif?: Card["whatif"];
  readonly certain?: Certain;
  readonly five_numbers?: FiveNumbers;
  readonly floor?: Card["floor"];
  readonly spend?: SpendCheck | null;
  readonly predicted?: Card["predicted"];
  readonly measurement_plan?: MeasurementPlan;
  readonly execution_sheet?: ExecutionSheet;
  readonly notes?: readonly string[];
  /** P91 D-9: a Gửi mẫu / Mời KOL version's KOL block (its product, samples, expected orders). */
  readonly kol?: KolBlock;
  /** Inputs that differ from V1 without changing the result, named ("Giới hạn 20 lượt không đổi kết quả: …"). */
  readonly same_as_default_notes?: readonly string[];
  readonly freshness?: Freshness;
}

/** A floor or spend-cap breach, as the backend lists it (`versions.breaches_of`, `manual.breaches_of`). */
export interface Breach {
  readonly type: "floor" | "spend_cap" | string;
  readonly sku?: string;
  readonly kind?: string;
  readonly floor?: N;
  readonly min_unit_price?: N;
  readonly spend_after?: N;
  readonly spend_per_day_after?: N;
  readonly cap?: N;
  readonly [extra: string]: unknown;
}

export interface Card {
  readonly id?: string;
  readonly code?: string | null;
  readonly product_queue?: number | null;
  readonly versions?: readonly CardVersion[];
  /** The version the top-level evaluation fields are (1 when omitted). */
  readonly version?: number;
  readonly origin?: string | null;
  readonly acknowledged_breaches?: { readonly at?: string; readonly breaches?: readonly Breach[]; readonly by?: unknown } | null;
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
  readonly freshness?: Freshness;
  readonly bundle: boolean;
  /** P91 D-9: set on Gửi mẫu / Mời KOL cards. */
  readonly kol?: KolBlock;
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
  /** P91 (assumed on the detail): which version was approved, and the breaches the seller acknowledged. */
  readonly chosen_version?: number | null;
  readonly chosen_version_code?: string | null;
  readonly acknowledged_breaches?: { readonly at?: string; readonly breaches?: readonly Breach[] } | null;
  readonly journey: readonly JourneyEvent[];
  /**
   * What the seller approved when they moved the sliders. `execution_sheet` is the sheet of those final
   * values; when the API does not send it the screen recomputes it from `inputs`.
   */
  readonly approved_with?: { readonly inputs: Readonly<Record<string, unknown>>; readonly execution_sheet?: ExecutionSheet };
}

export interface DecideResult {
  readonly id: string;
  readonly code?: string | null;
  readonly status: CardStatus;
  readonly approval_id: string;
  readonly chosen_version?: number;
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

// ── P91 D-3: Tự tạo phương án / So sánh phương án ───────────────────────────

export type DiscountType = "pct" | "amount" | "fixed_price";

export interface VariantInput {
  readonly label?: string;
  readonly change_kind: string;
  readonly items: readonly string[];
  readonly extra: {
    readonly addon_item?: string;
    readonly gift_item?: string;
    readonly combo_items?: readonly { readonly item_id: string; readonly sku?: string; readonly qty: number }[];
    readonly discount_type?: DiscountType;
    readonly discount_value?: number;
    readonly voucher?: { readonly value?: number; readonly pct?: number; readonly min_spend: number; readonly max_value?: number };
  };
  readonly inputs: Readonly<Record<string, unknown>>;
}

/** `manual.metrics_of`: every number is a change per month against doing nothing. */
export interface VariantMetrics {
  readonly dprofit_p10: N;
  readonly dprofit_p50: N;
  readonly dprofit_p90: N;
  readonly dprofit_certain: N;
  readonly dgmv_p50: N;
  readonly dorders_p50: N;
  readonly aov_p25: N;
  readonly margin_points_p25: N;
  readonly cost_month: N;
  readonly floor_breaches: number;
  readonly floor_ok: boolean;
  readonly spend_after_per_day?: N;
  readonly spend_cap?: N;
  readonly spend_over_cap?: boolean | null;
  /** Per day / per order / over the change's own days (the card's "period"). */
  readonly period_days?: number;
  readonly dprofit_per_day_p50?: N;
  readonly dgmv_per_day_p50?: N;
  readonly cost_per_day?: N;
  readonly dprofit_period_p10?: N;
  readonly dprofit_period_p50?: N;
  readonly dprofit_period_p90?: N;
  readonly cost_period?: N;
  readonly dprofit_per_order_p50?: N;
  readonly usage_expected?: N;
  readonly usage_limit?: N;
  readonly usage_capped?: boolean | null;
}

export interface VariantRow {
  readonly index: number;
  readonly label: string;
  readonly change_kind: string;
  readonly ok: boolean;
  readonly refusal: { readonly code: string; readonly message: string } | null;
  readonly title: string | null;
  readonly metrics: VariantMetrics | null;
  readonly card: Card | null;
}

export interface CompareResult {
  readonly today: {
    readonly as_of: string;
    readonly gmv_30d: number;
    readonly orders_30d: number;
    readonly aov: N;
    readonly margin_pct: N;
    readonly spend_per_day: N;
    readonly spend_cap: N;
  };
  readonly variants: readonly VariantRow[];
  readonly vs_today: readonly { readonly index: number; readonly delta: Readonly<Record<string, N>> }[];
  readonly between: readonly { readonly from: number; readonly to: number; readonly delta: Readonly<Record<string, N>>; readonly notes?: readonly string[] }[];
  readonly best_profit_p50: number | null;
  readonly saved: false;
}

export interface ManualInput {
  readonly variants: readonly VariantInput[];
  readonly chosen: number;
  readonly primary: boolean;
  readonly acknowledgeBreaches: boolean;
}

export interface ManualResult {
  readonly id: string;
  readonly status: CardStatus;
  readonly origin: "manual";
  readonly position: number;
  readonly primary: boolean;
  /** `manual._version_row` (not the engine's version shape): `index`, `chosen`, `label`, `metrics`… */
  readonly versions: readonly { readonly index: number; readonly chosen: boolean; readonly label: string; readonly metrics: VariantMetrics | null }[];
  readonly card: Card;
}

/** `GET …/recommendations/code/{code}` (Ops): one card by code, everything a row of the later export needs. */
export interface CardByCode {
  readonly code: string;
  readonly id: string;
  readonly status: CardStatus;
  readonly cycle?: string;
  readonly family: Family;
  readonly change_kind: string;
  readonly title: string;
  readonly product_id: string | null;
  readonly product_queue: number | null;
  readonly created_at: string | null;
  readonly sent_at: string | null;
  readonly supersedes_code: string | null;
  readonly versions: readonly VersionBrief[];
  readonly chosen_version: number | null;
  readonly chosen_version_code: string | null;
  readonly inputs: { readonly default: Readonly<Record<string, unknown>>; readonly chosen?: Readonly<Record<string, unknown>> | null; readonly approved?: Readonly<Record<string, unknown>> | null };
  readonly change: { readonly target?: unknown; readonly before?: unknown; readonly after?: unknown };
  readonly status_history: readonly { readonly event: string; readonly at: string | null; readonly actor?: string; readonly reason_code?: string | null; readonly payload?: Readonly<Record<string, unknown>> }[];
  readonly verification: { readonly state: string | null };
  readonly selected_version?: CardVersion;
}
