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

export interface Overview {
  readonly generated_at: string;
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

export type OverrideKey =
  | "card_daily_limit"
  | "card_weekly_limit"
  | "card_open_limit"
  | "enabled_streams"
  | "enabled_actions"
  | "content_cards_enabled"
  | "promotion_api_enabled"
  | "openai_model"
  | "openai_monthly_cap_usd";

export type Overrides = { readonly [K in OverrideKey]: unknown };

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

export interface AuditEntry {
  readonly id: string;
  readonly at: string | null;
  readonly actor_email: string;
  readonly shop_id: string | null;
  readonly action: string;
  readonly before: unknown;
  readonly after: unknown;
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
  readonly band: BandStats | null;
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

export interface SimulationPage {
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
  readonly scenarios: readonly Scenario[];
}
