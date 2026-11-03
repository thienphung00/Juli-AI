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
  /** Migration 110: `shops.platform` ("tiktok" | "shopee"); absent = TikTok. */
  readonly platform?: string;
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
  | "kpi_shrinkage"
  /** P36 (D45.6): from this many measured products a group reads two pre-period windows (15). */
  | "group_two_window_min"
  /** P36 (D45.2): warn when a group's product-card CTR falls more than this, points of % (15). */
  | "group_guard_ctr_drop"
  /** P36 (D45.4): weekly drift σ behind a group's drift floor (0.15). */
  | "group_drift_sigma"
  /** P45 (D52): default prior SD of the EB-shrunk group log-lift (0.15). */
  | "group_eb_prior_sd"
  /** P45 (D52): from this many measured groups (shops) of a lever type the EB prior is pooled (3). */
  | "group_eb_min_groups";

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
  /** Migration 110: `shops.platform` ("tiktok" | "shopee"); absent = TikTok. */
  readonly platform?: string;
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
  /** P36 (D45.8): "high" / "low" order-volume stratum of a stratified Ops group. */
  readonly stratum?: string | null;
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

/** P45 (D52, Ops only): the comparison's lift shrunk toward its lever type's prior (empirical Bayes). */
export interface CardGroupEb {
  readonly observed_log_lift: number;
  readonly se: number;
  /** The raw lift as a ratio, % (100 (e^y − 1)). */
  readonly observed_pct: number;
  /** w = τ² / (τ² + se²). */
  readonly weight: number;
  readonly shrunk_log_lift: number;
  readonly shrunk_pct: number;
  /** 90 % interval of the shrunk lift, %. */
  readonly interval_pct: readonly [number, number];
  /** "default": N(0, sd²); "pooled": DerSimonian–Laird over n_groups measured groups (one per shop),
   * from the D14 cell "lever_type" (lever × metric × channel) or the wider "metric_channel";
   * "own": the shop has no pooled_training grant and borrows nothing. */
  readonly prior: {
    readonly source: "default" | "pooled" | "own";
    readonly mean: number;
    readonly tau: number;
    readonly n_groups: number;
    readonly cell?: "lever_type" | "metric_channel";
  };
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
  /** P45 (D52, Ops only): absent on verdicts stored before P45 (the Ops route fills it); null without numbers. */
  readonly eb?: CardGroupEb | null;
}

/** P36 (D45.6): which pre-period rule adjusted the changes. */
export interface CardGroupAdjustment {
  readonly method: "change" | "one_window" | "two_windows";
  readonly theta: number;
  readonly theta_pre: number | null;
  /** null: the P31 rule (a card group's client-facing verdict). */
  readonly two_window_min: number | null;
}

/** P36 (D45.2): one more metric read the same way as the primary (all-channel AOV, items per order, card CTR). */
export interface CardGroupMetric {
  readonly metric: string;
  readonly channel: string;
  /** "AOV · tất cả kênh"; P46 (D55.1): money metrics name the basis, "AOV (đã trừ huỷ/hoàn) · tất cả kênh". */
  readonly label: string;
  readonly primary: CardGroupComparison | null;
  readonly adjustment?: CardGroupAdjustment | null;
  readonly false_alarm?: CardGroupFalseAlarm | null;
  /** P46 (D55.1): "net" (cancelled / refunded orders removed) or "gross" (TikTok GMV); null for CTR / CTOR. */
  readonly basis?: "net" | "gross" | null;
  /** P46 (D55.1): the same comparison on TikTok GMV (incl. cancelled / refunded orders), when this one is net. */
  readonly gross?: CardGroupMetric;
}

/** P46 (D55.1, Ops only): which basis a verdict's money metrics (AOV, items per order) were read on. */
export interface CardGroupBasis {
  readonly money: "net" | "gross";
  readonly text: string;
}

/** P36 (D45.2): the product-card CTR guard of a group whose primary metric is not CTR. */
export interface CardGroupGuard {
  readonly metric: string;
  readonly channel: string;
  readonly max_drop_pct: number;
  readonly difference: number | null;
  readonly primary_difference: number | null;
  readonly warning: boolean;
  readonly text: string;
}

export interface CardGroupVerdict {
  readonly as_of: string;
  readonly window_days: number;
  readonly primary: CardGroupComparison;
  readonly approved_only: CardGroupComparison;
  /** P36: optional, absent on verdicts stored before P36. */
  readonly adjustment?: CardGroupAdjustment;
  readonly metrics?: Readonly<Record<string, CardGroupMetric>>;
  readonly guard?: CardGroupGuard;
  /** P36 (D45.6, Ops only): a card group's primary metric read with the group-size rule; the seller's sentence keeps the P31 rule. */
  readonly ops_rule?: CardGroupMetric;
  /** P46 (D55.1, Ops only): absent on verdicts stored before P46. */
  readonly basis?: CardGroupBasis;
  /** P46: an Ops group's money primary read on TikTok GMV (the primary itself is net). */
  readonly gross?: CardGroupMetric;
  /** P46: a card group's money primary read net (the primary, behind the seller's sentence, stays on TikTok GMV). */
  readonly net?: CardGroupMetric;
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
  /** P36 (D45): who made the group, the one-line reason, the CTR guard; optional until the backend sends it. */
  readonly design?: CardGroupDesign;
  /** P36 (D45.4): the weekly-drift floor of the 90 % interval and the traffic needed. */
  readonly plan?: CardGroupPlan;
}

export interface CardGroupDesign {
  /** "cards": drawn from Optimize Product drafts; "ops": made in Ops (no cards, the seller never sees it). */
  readonly source: "cards" | "ops";
  readonly reason: string | null;
  readonly guard: boolean;
  readonly created_by: string | null;
  /** P36 (D45.8): product → "high" / "low" by 30-day orders; null = one draw. */
  readonly strata?: Readonly<Record<string, string>> | null;
  readonly strata_orders?: Readonly<Record<string, number>> | null;
}

export interface CardGroupPlan {
  readonly weeks: number;
  readonly sigma_week: number;
  readonly n_treated: number;
  readonly n_control: number;
  /** % half-widths: whole group before vs after (the research's number), and treated − control. */
  readonly floor: { readonly pooled_pct: number; readonly difference_pct: number | null } | null;
  readonly needed_per_arm: {
    readonly unit: "impressions" | "orders";
    readonly half_width_pct: number;
    readonly no_drift: number;
    readonly with_drift: number | null;
    readonly reachable: boolean;
  } | null;
  /** The 14 days before launch, per arm. */
  readonly have_before: Readonly<
    Record<
      "treated" | "control",
      {
        readonly impressions: number;
        readonly clicks: number;
        readonly orders: number;
        /** TikTok GMV: includes cancelled and refunded orders. */
        readonly gmv: number;
        /** P46 (D55.1): net of cancelled / refunded orders, when the shop's orders cover the window. */
        readonly orders_net?: number;
        readonly gmv_net?: number;
      }
    >
  >;
  readonly have_window: readonly [string, string];
  /** P46 (D55.1): "net" when have_before carries gmv_net / orders_net; absent before P46. */
  readonly revenue_basis?: "net" | "gross";
}

/** `POST /v1/ops/shops/{id}/groups` (P36, D45.1). */
export interface CardGroupCreate {
  readonly lever: string;
  readonly metric: string;
  readonly channel: string;
  readonly product_ids: readonly string[];
  readonly reason: string | null;
  /** null: on unless the metric is CTR. */
  readonly guard: boolean | null;
  /** D45.8: draw within high / low order-volume strata (2 treated + 1 control each for 3 + 3). */
  readonly stratify?: boolean;
}

/** `GET /v1/ops/shops/{id}/groups`. */
export interface CardGroupsPage {
  readonly enabled: boolean;
  readonly groups: readonly CardGroup[];
}

/* -- P33-F (D43): tab "Đăng ký dùng thử" — app-juli.com/dang-ky sign-ups ------------- */

export type TrialSignupStatus = "new" | "contacted" | "converted" | "spam";

export interface TrialSignup {
  readonly id: string;
  readonly created_at: string | null;
  readonly full_name: string;
  readonly phone: string;
  readonly email: string;
  readonly shop: string;
  readonly role: string;
  readonly role_label: string;
  readonly note: string | null;
  readonly source: Readonly<Record<string, string>>;
  readonly status: TrialSignupStatus;
  readonly status_label: string;
  readonly handled_by: string | null;
  readonly handled_at: string | null;
}

export interface TrialSignupsPage {
  readonly data: readonly TrialSignup[];
  readonly counts: Readonly<Record<TrialSignupStatus, number>>;
  readonly statuses: readonly { readonly value: TrialSignupStatus; readonly label: string }[];
}

/** Contract-client shops (ADR-118): the Terms scopes' open grants, and whether Ops may press "Bật". */
export interface ShopConsent {
  readonly scopes: Readonly<Record<string, boolean>>;
  readonly enabled: boolean;
  readonly contract_client: boolean;
  readonly granted?: readonly string[];
}

export interface ContractShop {
  readonly id: string;
  readonly shop_name: string;
  readonly platform: string;
  readonly shopee_shop_id: string | null;
}

/** ADR-118 "Tạo mã kết nối": the one-use code (shown once) and the connected sources. */
export interface PairingCode {
  readonly code: string;
  readonly expires_at: string;
  readonly ttl_seconds: number;
}

export interface IngestTokenRow {
  readonly id: string;
  readonly client_label: string | null;
  readonly created_at: string;
  readonly expires_at: string;
  readonly last_used_at: string | null;
  readonly revoked_at: string | null;
  readonly active: boolean;
}

/** ADR-118 "Chu kỳ": proposals of a shop's manual cycle (`GET /v1/ops/shops/{id}/proposals`). */
export type ProposalKind = "title" | "images" | "price" | "voucher" | "flash_sale" | "ads" | "bundle" | "program" | "stock" | "other";
export type ProposalSubject = "item" | "shop" | "campaign";
export type ProposalStatus = "draft" | "sent" | "approved" | "rejected" | "changes_requested" | "executed" | "measured" | "withdrawn" | "superseded";
export type ApprovalDecision = "approved" | "rejected" | "changes_requested";
export type ApprovalChannel = "email" | "document";
export type ExecutorRole = "client_representative" | "juli_operator";

export interface ProposalApproval {
  readonly id: string;
  readonly decision: ApprovalDecision | string;
  readonly channel: string;
  readonly evidence_ref: string | null;
  readonly note: string | null;
  readonly decided_at: string | null;
}

export interface ProposalExecution {
  readonly id: string;
  readonly executed_at: string | null;
  readonly executor_role: string;
  readonly channel: string;
  readonly evidence_ref: string | null;
  readonly verified_at: string | null;
  readonly verified_how: string | null;
}

/** D81: one metric of a measured proposal against the item's own history (Ops only). */
export type ProposalMetric = "impressions" | "clicks" | "ctr";
export type ResultVerdict = "dat" | "khong_dat" | "chua_ket_luan";

export interface ProposalResult {
  readonly metric: ProposalMetric | string;
  readonly verdict: ResultVerdict | string;
  /** The post week's value (daily average; CTR as a fraction). */
  readonly value: number | null;
  /** The 28-day baseline's value. */
  readonly comparison: number | null;
  /** value / (max of the last 8 weekly values) - 1. */
  readonly band: number | null;
  readonly pre_from: string | null;
  readonly pre_to: string | null;
  readonly post_from: string | null;
  readonly post_to: string | null;
  readonly data_through: string | null;
  readonly computed_at: string | null;
}

export interface ShopProposalRow {
  readonly id: string;
  readonly revision: number;
  readonly cycle: string;
  readonly kind: ProposalKind | string;
  readonly subject_type: ProposalSubject | string;
  readonly item_id: string | null;
  readonly subject_label: string;
  readonly change_before: Record<string, unknown>;
  readonly change_after: Record<string, unknown>;
  readonly reason: string;
  readonly planned_start: string | null;
  readonly status: ProposalStatus | string;
  readonly platform: string;
  readonly supersedes_id: string | null;
  readonly sent_at: string | null;
  readonly created_at: string | null;
  readonly approvals: readonly ProposalApproval[];
  readonly executions: readonly ProposalExecution[];
  /** Newest result per metric; empty before the first measurement. */
  readonly results?: readonly ProposalResult[];
}

export interface ProposalCreate {
  readonly cycle: string;
  readonly kind: ProposalKind;
  readonly subject_type: ProposalSubject;
  readonly item_id: string | null;
  readonly subject_label: string;
  readonly change_before: Record<string, unknown>;
  readonly change_after: Record<string, unknown>;
  readonly reason: string;
  readonly planned_start: string | null;
}

export interface ApprovalCreate {
  readonly decision: ApprovalDecision;
  readonly channel: ApprovalChannel;
  readonly evidence_ref: string;
  readonly decided_at: string;
  readonly note: string | null;
}

export interface ExecutionCreate {
  readonly executed_at: string;
  readonly executor_role: ExecutorRole;
  readonly evidence_ref: string | null;
}

/** ADR-117 step 4: the Shopee dashboards (`/v1/ops/shops/{id}/shopee/*`), measured data only. */
export type ShopeeOrderType = "placed" | "paid" | "confirmed";

export interface ShopeeRange {
  readonly from: string;
  readonly to: string;
}

export interface ShopeeFlowCell {
  readonly gmv: number | null;
  readonly orders: number | null;
  readonly impressions: number | null;
  readonly clicks: number | null;
  readonly buyers: number | null;
}

export interface ShopeeFlowChild extends ShopeeFlowCell {
  readonly segment: string;
  readonly label: string;
}

export interface ShopeeFlow extends Partial<ShopeeFlowCell> {
  readonly stream: string;
  readonly label: string;
  readonly has_total_row: boolean;
  /** G3: a child ("Trang shop" under "Thẻ sản phẩm") is a breakdown, never added to the total. */
  readonly children: ShopeeFlowChild[];
}

export interface ShopeeMonth {
  readonly month: string;
  readonly gmv: number | null;
  readonly orders: number | null;
}

export interface ShopeeFlows {
  readonly range: ShopeeRange;
  readonly order_type: ShopeeOrderType;
  readonly total_gmv: number;
  readonly total_orders: number;
  readonly flows: ShopeeFlow[];
  readonly ads_overlay: { readonly stream: string; readonly label: string; readonly gmv: number; readonly orders: number; readonly in_total: false } | null;
  readonly monthly: { readonly month: string; readonly streams: Record<string, number | null>; readonly shop_page_gmv: number | null }[];
  readonly shop_monthly: ShopeeMonth[];
  readonly has_data: boolean;
}

export interface ShopeeProduct {
  readonly item_id: string;
  readonly name: string | null;
  readonly impressions: number | null;
  readonly clicks: number | null;
  readonly visitors: number | null;
  readonly page_views: number | null;
  readonly add_to_cart: number | null;
  readonly orders: number | null;
  readonly gmv: number | null;
  readonly units: number | null;
  readonly buyers: number | null;
  readonly ctr: number | null;
  readonly add_to_cart_rate: number | null;
  readonly click_to_order: number | null;
  readonly by_flow: Record<string, { readonly gmv: number | null; readonly orders: number | null }>;
  readonly history: ShopeeMonth[];
  readonly flags: { readonly flag: string; readonly label: string; readonly from: string; readonly to: string }[];
}

export interface ShopeeProducts {
  readonly order_type: ShopeeOrderType;
  readonly period: ShopeeRange | null;
  readonly periods: { readonly from: string; readonly to: string; readonly items: number }[];
  readonly items_total: number;
  readonly totals: Omit<ShopeeProduct, "item_id" | "name" | "by_flow" | "history" | "flags"> | null;
  readonly products: ShopeeProduct[];
  readonly shop_monthly: ShopeeMonth[];
  readonly has_data: boolean;
}

export interface ShopeeAdCell {
  readonly cost: number | null;
  readonly orders: number | null;
  readonly gmv: number | null;
  readonly roas: number | null;
  readonly cost_per_order: number | null;
}

export interface ShopeeAdType extends ShopeeAdCell {
  readonly ad_type: string;
  readonly label?: string;
}

export interface ShopeeAds {
  readonly range: ShopeeRange;
  readonly order_type: ShopeeOrderType;
  readonly total: ShopeeAdCell;
  readonly by_type: ShopeeAdType[];
  readonly daily: { readonly day: string; readonly by_type: ShopeeAdType[] }[];
  readonly monthly: ({ readonly month: string; readonly by_type: ShopeeAdType[] } & ShopeeAdCell)[];
  readonly campaigns: ShopeeAdType[];
  readonly campaigns_available: boolean;
  readonly alerts: { readonly ad_type: string; readonly label: string; readonly days: number; readonly from: string; readonly to: string; readonly roas: number | null; readonly floor: number }[];
  readonly alert_rule: { readonly floor: number; readonly min_days: number };
  readonly has_data: boolean;
}

export interface ShopeePromotions {
  readonly range: ShopeeRange;
  readonly order_type: ShopeeOrderType;
  readonly programs: {
    readonly promo_type: string;
    readonly type_label: string;
    readonly name: string;
    readonly starts_at: string;
    readonly ends_at: string | null;
    readonly status: string | null;
    readonly gmv: number | null;
    readonly orders: number | null;
    readonly units: number | null;
    readonly buyers: number | null;
  }[];
  readonly daily: { readonly day: string; readonly promo_type: string; readonly type_label: string; readonly gmv: number | null; readonly orders: number | null }[];
  readonly has_data: boolean;
}

export interface ShopeeQuery {
  readonly from?: string;
  readonly to?: string;
  readonly orderType?: ShopeeOrderType;
  readonly periodFrom?: string;
  readonly periodTo?: string;
}
