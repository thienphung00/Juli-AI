import type { ChangeStrength } from "../change-strength";

/** Shapes of `/v1/ops/*` (contract `fasttrack/contracts/p16-ops.md`). */

export type StageId = "trial" | "self" | "pilot";
export type RoleId = "viewer" | "operator" | "admin";
export type Connection = "ok" | "expired" | "none";

export interface OpsMe {
  readonly email: string;
  readonly role: RoleId;
  readonly role_label: string;
}

export interface OverviewShop {
  readonly shop_id: string;
  readonly shop_name: string;
  readonly tiktok_shop_id: string | null;
  readonly owner_email: string | null;
  readonly owned_by_team: boolean;
  readonly invite_pending: boolean;
  readonly stage: StageId;
  readonly stage_label: string;
  readonly connection: Connection;
  readonly active: boolean;
  readonly last_poll_at: string | null;
  readonly last_diagnosis_at: string | null;
  readonly cards_open: number;
  readonly cards_approved_30d: number;
  readonly cards_rejected_30d: number;
  readonly approval_rate: number | null;
  readonly failed_runs_30d: number;
  readonly openai_cost_month_usd: number;
  readonly openai_cap_usd: number | null;
  readonly openai_cap_reached: boolean;
  readonly gmv_30d: number | null;
  readonly permissions?: Permissions | null;
}

export interface Permissions {
  readonly status: "complete" | "missing" | "unknown" | "not_connected";
  readonly missing: readonly { scope: string; used_for: string }[];
  readonly needs_reconnect: boolean;
}

/** D27.1 freshness: when the daily precompute ran and the last day it covers. Optional (older backend). */
export interface Freshness {
  readonly generated_at?: string | null;
  readonly data_through?: string | null;
}

export interface Overview extends Freshness {
  readonly totals: {
    readonly accounts: number;
    readonly connected: number;
    readonly active: number;
    readonly disconnected: number;
    readonly cards_approved_30d: number;
    readonly approval_rate_30d: number | null;
    readonly openai_cost_month_usd: number;
    readonly openai_cap_alerts: number;
  };
  readonly shops: readonly OverviewShop[];
}

/** P23 (D29.11): per-shop diagnosis & KPI tunables; optional until the backend sends them. */
export type DiagKey =
  | "diag_windows"
  | "diag_min_events"
  | "kpi_min_band_mult"
  | "kpi_max_band_mult"
  | "guard_band_mult"
  | "volatile_cv"
  /** P30 (D39.1): "metric_first" (default) | "gmv_first" (rollback). */
  | "diag_trigger"
  /** P31 (D41.2): "on" (default) | "off" -- shrink CTR / CTOR toward the category before the trigger. */
  | "kpi_shrinkage";

/** P28 (D33): the per-shop "many cards" quota mode; optional until the backend sends them. */
export type QuotaKey =
  | "card_quota_mode"
  | "card_quota_per_cell"
  | "card_quota_max_open"
  /** P30 (D34 / D39.3): group A/B with a delayed control; null follows card_quota_mode. */
  | "card_groups";

export type OverrideKey =
  | DiagKey
  | QuotaKey
  | "card_daily_limit"
  | "card_weekly_limit"
  | "card_open_limit"
  | "enabled_streams"
  | "enabled_actions"
  | "content_cards_enabled"
  | "promotion_api_enabled"
  | "openai_model"
  | "openai_monthly_cap_usd";

export type Overrides = { readonly [K in Exclude<OverrideKey, DiagKey | QuotaKey>]: unknown } & {
  readonly [K in DiagKey | QuotaKey]?: unknown;
};

export interface ShopSettings {
  readonly shop_id: string;
  readonly stage: StageId;
  readonly stage_label: string;
  readonly overrides: Overrides;
  readonly defaults: Overrides;
  readonly updated_at: string | null;
  readonly options: {
    readonly stages: readonly { id: StageId; label: string }[];
    readonly streams: readonly { id: string; label: string }[];
    readonly actions: readonly string[];
    readonly models: readonly string[];
  };
}

/** D27.4 audit groups (Nhật ký filter chips). */
export type AuditKind = "config" | "view" | "system";

export interface AuditEntry {
  readonly id: string;
  readonly at: string | null;
  readonly actor_email: string;
  readonly shop_id: string | null;
  readonly action: string;
  readonly before: unknown;
  readonly after: unknown;
  /** D27: optional so an older backend still parses. */
  readonly kind?: AuditKind | null;
  /** D27.6: how many changes within 10 minutes were merged into this row (≥ 1). */
  readonly merged_count?: number | null;
  readonly shop_name?: string | null;
}

export interface Invite {
  readonly id: string;
  readonly email: string;
  readonly keep_ops_access: boolean;
  readonly expires_at: string;
  readonly created_at: string | null;
  readonly accepted_at: string | null;
  readonly seller_kept_ops_access: boolean | null;
  readonly revoked_at: string | null;
}

export interface ShopInfo {
  readonly shop_id: string;
  readonly shop_name: string;
  readonly owner_email: string | null;
  readonly owned_by_team: boolean;
  readonly staff_access_consent_at: string | null;
}

export interface ShopSettingsPage {
  readonly shop: ShopInfo;
  readonly settings: ShopSettings;
  readonly invites: readonly Invite[];
  readonly audit: readonly AuditEntry[];
  /** P28 (D33): open cards per cell ("ctr@product_card" → 3); only while the quota mode is on. */
  readonly card_cells?: Readonly<Record<string, number>> | null;
}

export interface ViewSession {
  readonly shop: ShopInfo;
  readonly stage: StageId;
  readonly read_only: true;
}

export interface DisconnectResult {
  readonly already_disconnected: boolean;
  readonly credentials_revoked: number;
  readonly runs_cancelled: number;
  readonly email_sent: boolean;
  readonly tiktok_revoke: string;
}

export type StreamId = "product_card" | "shop_tab" | "seller_video" | "seller_live";
export type KpiId = "impressions" | "ctr" | "ctor" | "aov";
export type Deltas = Partial<Record<StreamId, Partial<Record<KpiId, number>>>>;

export interface BandStats {
  readonly p10: number;
  readonly p90: number;
  readonly mean: number;
  readonly band_pct: number | null;
  readonly cv: number | null;
  readonly days: number;
}

export interface SimCell {
  readonly kpi: KpiId;
  readonly label: string;
  readonly value: number | null;
  readonly trend_pct: number | null;
  /** D31.7: the trend against both windows' bands combined; null / absent: show nothing. */
  readonly trend_strength?: ChangeStrength | null;
  /** D28.1: band of the window mean (older backends: the daily p10–p90 band). */
  readonly band: BandStats | null;
  /** D28.1: the daily p10–p90 band, shown on hover / click. Absent on older backends. */
  readonly daily_band?: BandStats | null;
  /** D28.2: the window's summed clicks (CTR) / SKU orders (CTOR, AOV); null for Hiển thị. */
  readonly events?: number | null;
  readonly event_kind?: "click" | "order" | null;
  /** D28.2: fewer than 30 events in the window. */
  readonly low_data?: boolean;
  readonly locked: boolean;
  readonly indirect: boolean;
  readonly actions: string | null;
}

export type Stability = "stable" | "medium" | "volatile" | "unknown";

export interface SimStream {
  readonly stream: StreamId;
  readonly name: string;
  readonly days_present: number;
  readonly gmv_per_day: number | null;
  readonly gmv_model_per_day: number;
  readonly impressions_cv: number | null;
  readonly stability: Stability;
  readonly cells: readonly SimCell[];
}

export interface VolatilityRow {
  readonly id: string;
  readonly name: string;
  readonly impressions: BandStats;
  readonly ctr: BandStats | null;
  readonly ctor: BandStats | null;
  readonly impressions_cv: number | null;
  readonly stability: Stability;
}

export interface WindowStatus {
  readonly days: number;
  readonly baseline_available: boolean;
  readonly comparable: boolean;
  readonly needs_days: number;
  readonly history_days: number;
}

export interface SimResult {
  readonly streams: Record<StreamId, { gmv_base: number; gmv_new: number; delta_pct: number | null }>;
  readonly total_base: number;
  readonly total_new: number;
  readonly delta_pct: number | null;
  readonly delta_per_day: number;
  readonly delta_per_month: number;
}

export interface Scenario {
  readonly id: string;
  readonly name: string;
  readonly deltas: Deltas;
  readonly is_target: boolean;
  readonly created_at: string | null;
  readonly result?: SimResult | null;
}

export interface SimulationPage extends Freshness {
  readonly shop: ShopInfo;
  readonly stage: StageId;
  readonly window: number;
  readonly windows: readonly WindowStatus[];
  readonly from: string | null;
  readonly to: string | null;
  readonly status: WindowStatus;
  readonly streams: readonly SimStream[];
  readonly volatility: Partial<Record<StreamId, { row_kind: string; rows: readonly VolatilityRow[] }>>;
  readonly lever_map: Partial<Record<StreamId, Partial<Record<KpiId, string>>>>;
  readonly step_pct: number;
  /** True when the shop had no per-day data and a report rebuild was queued. */
  readonly rebuilding?: boolean;
  readonly scenarios: readonly Scenario[];
}

/* -- D28.3 tab "Chi phí" (`/v1/ops/costs*`) ------------------------------------------ */

export interface SystemCost {
  readonly month: string;
  readonly used_usd: number;
  readonly cap_usd: number;
  readonly cap_is_default: boolean;
  readonly cap_updated_at: string | null;
  readonly cap_updated_by: string | null;
  /** used / cap as a fraction (0.82 = 82 %). */
  readonly pct: number;
  /** 80 (≥ 80 %), 100 (reached) or null. */
  readonly level: 80 | 100 | null;
  readonly reached: boolean;
  /** This month's alert e-mail went out to the Admins. */
  readonly alert_sent?: boolean;
}

export type ShopCostState = "ok" | "shop_cap" | "system_cap";

export interface ShopCost {
  readonly shop_id: string;
  readonly shop_name: string;
  readonly stage: StageId;
  readonly stage_label: string;
  readonly used_usd: number;
  readonly cap_usd: number;
  /** A cap set for this shop ("· riêng"); false = the default. */
  readonly is_custom: boolean;
  readonly state: ShopCostState;
}

export interface CostsPage {
  readonly system: SystemCost;
  readonly warn_pct: number;
  readonly days_left_in_month: number;
  readonly default_shop_cap_usd: number;
  readonly seller_paused_text: string;
  readonly shops: readonly ShopCost[];
}

/* -- D28.4 tab "Thời hạn" (`/v1/ops/terms`, `/v1/ops/shops/{id}/terms`) ----------------- */

export type TermState = "none" | "ok" | "soon" | "grace" | "read_only";

export interface Term {
  readonly state: TermState;
  readonly expires_on: string | null;
  readonly days_left: number | null;
  readonly grace_days_left: number | null;
}

export interface SubscriptionPeriod {
  readonly id: string;
  readonly plan: "month" | "year";
  readonly days: 30 | 365;
  readonly starts_on: string;
  readonly ends_on: string;
  readonly source: "contract" | "payment";
  readonly reference: string;
  readonly actor_email: string | null;
  readonly created_at: string | null;
}

export interface ShopTermRow extends Term {
  readonly shop_id: string;
  readonly shop_name: string;
  readonly stage: StageId;
  readonly stage_label: string;
  readonly latest_period: SubscriptionPeriod | null;
}

export interface TermsPage {
  readonly today: string;
  readonly soon_days: number;
  readonly grace_days: number;
  readonly shops: readonly ShopTermRow[];
}

export interface ShopTermsPage {
  readonly shop: ShopInfo;
  readonly today: string;
  readonly term: Term;
  readonly periods: readonly SubscriptionPeriod[];
  readonly created?: boolean;
  readonly period?: SubscriptionPeriod;
}

/** P30 (D34 / D39.3): one product of a card group and its arm (intent-to-treat). */
export interface CardGroupMember {
  readonly product_id: string;
  readonly product_title: string | null;
  readonly arm: "treated" | "control";
  readonly card_id: string | null;
  readonly card_status: string | null;
  readonly surfaced_at: string | null;
  readonly approved: boolean;
  readonly released_at: string | null;
}

/** P31 (D41.3): the group's simulated false-alarm rate (500 no-effect replays). */
export interface CardGroupFalseAlarm {
  readonly rate: number;
  readonly max: number;
  readonly acceptable: boolean;
  readonly draws: number;
  /** P31 T3.1: pre-period pairs, plus the control's untouched post-launch pairs once measured. */
  readonly source: "pre_period" | "pre_period+control_after" | "centred_changes";
  readonly pool: number;
}

/** Median change treated − control (points of %), its 90 % (P31; 80 % before) bootstrap interval and wording. */
export interface CardGroupComparison {
  readonly n_treated: number;
  readonly n_control: number;
  /** null: a full verdict; "Sơ bộ"; "Đang đo" (P31: false-alarm rate > 10 %, no strength); "Chưa đủ cơ sở" (no numbers). */
  readonly label: string | null;
  readonly median_treated: number | null;
  readonly median_control: number | null;
  readonly difference: number | null;
  readonly interval: readonly [number, number] | null;
  readonly strength: "clear" | "likely" | "noise" | null;
  readonly strength_label: string | null;
  /** P31 (D41.3): optional, absent on verdicts stored before P31. */
  readonly test?: "permutation" | "bootstrap";
  readonly permutation?: { readonly p_value: number; readonly draws: number; readonly exact: boolean } | null;
  readonly false_alarm?: CardGroupFalseAlarm | null;
}

export interface CardGroupVerdict {
  readonly as_of: string;
  readonly window_days: number;
  readonly primary: CardGroupComparison;
  readonly approved_only: CardGroupComparison;
  readonly products: readonly {
    readonly product_id: string;
    readonly arm: "treated" | "control";
    readonly approved: boolean;
    readonly before: number | null;
    readonly after: number | null;
    readonly change_pct: number | null;
  }[];
}

export interface CardGroup {
  readonly id: string;
  readonly key: string;
  /** "CTR · Ảnh bìa · Thẻ sản phẩm". */
  readonly label: string;
  readonly metric: string;
  readonly lever: string;
  readonly channel: string;
  readonly launched_on: string;
  readonly release_on: string;
  readonly seed: number;
  readonly status: "open" | "measured";
  readonly treated: number;
  readonly control: number;
  readonly members: readonly CardGroupMember[];
  readonly verdict: CardGroupVerdict | null;
  /** P31 (D41.3): the primary verdict's simulated false-alarm rate; absent before P31. */
  readonly false_alarm?: CardGroupFalseAlarm | null;
  readonly seller_sentence: string | null;
}

/** `GET /v1/ops/shops/{id}/groups`. */
export interface CardGroupsPage {
  readonly enabled: boolean;
  readonly groups: readonly CardGroup[];
}
