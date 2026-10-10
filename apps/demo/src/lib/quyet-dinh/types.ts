/**
 * Wire shapes of the P8-C routes Quyết định reads (backend
 * `api/routes/demo_rules.py`, `api/routes/demo_run_changes.py`), field for
 * field. Kept local to the demo app: no other app reads them yet.
 */

export type SetBy = "team" | "seller";

export interface RuleValueItem {
  readonly value: unknown;
  readonly set_by: SetBy | null;
  readonly set_by_user_id: string | null;
  readonly set_at: string | null;
}

export interface ShopRules {
  readonly stability_band: Readonly<Record<string, RuleValueItem>>;
  readonly product_cost: Readonly<Record<string, RuleValueItem>>;
  readonly max_discount_pct: Readonly<Record<string, RuleValueItem>>;
  readonly min_margin_pct: RuleValueItem | null;
  readonly max_open_cards: RuleValueItem;
  readonly auto_levers: RuleValueItem;
  readonly protected_terms: RuleValueItem;
  // D24.21 (5): the content runs' voice. Optional so an older backend parses.
  readonly content_tone?: RuleValueItem | null;
  readonly banned_terms?: RuleValueItem;
  readonly band_metrics: readonly string[];
  readonly listing_levers: readonly string[];
  // P14-F: what no TikTok API gives Juli. Optional so an older backend (or a
  // fixture written before P14) still parses; unset reads as "—".
  readonly sku_cost?: Readonly<Record<string, RuleValueItem>>;
  readonly default_gross_margin_pct?: RuleValueItem | null;
  readonly default_max_discount_pct?: RuleValueItem | null;
  readonly program_fee_pct?: RuleValueItem | null;
  readonly joins_platform_campaigns?: RuleValueItem | null;
  readonly platform_campaign_note?: RuleValueItem | null;
  readonly target_roas?: RuleValueItem | null;
  readonly gmv_max_daily_budget?: RuleValueItem | null;
  readonly live_schedule?: RuleValueItem | null;
  readonly weekdays?: readonly string[];
}

export type RuleKey =
  | "stability_band"
  | "product_cost"
  | "min_margin_pct"
  | "max_discount_pct"
  | "max_open_cards"
  | "auto_levers"
  | "protected_terms"
  | "content_tone"
  | "banned_terms"
  | "sku_cost"
  | "default_gross_margin_pct"
  | "default_max_discount_pct"
  | "program_fee_pct"
  | "joins_platform_campaigns"
  | "platform_campaign_note"
  | "target_roas"
  | "gmv_max_daily_budget"
  | "live_schedule";

export interface FieldChange {
  readonly field: string;
  readonly label: string;
  readonly before: unknown;
  readonly after: unknown;
  readonly after_source: string;
  readonly recorded_at: string | null;
}

export interface RevertRunItem {
  readonly run_id: string;
  readonly status: string;
  readonly stop_reason: string | null;
}

export interface BandBreach {
  readonly metric: string;
  readonly impact_pct: number;
  readonly band_pct: number;
}

export interface RevertQuestion {
  readonly id: string;
  readonly run_id: string;
  readonly status: string;
  readonly breaches: readonly BandBreach[];
  readonly created_at: string | null;
  readonly revert_run_id: string | null;
}

export interface RunChanges {
  readonly run_id: string;
  readonly reverts_run_id: string | null;
  readonly changes: readonly FieldChange[];
  readonly revert: {
    readonly available: boolean;
    readonly reason_code: string | null;
    readonly message: string | null;
    readonly runs: readonly RevertRunItem[];
  };
  readonly question: RevertQuestion | null;
}

/** The bands the seller (or the team for them) actually set — defaults never count. */
export function setBands(rules: ShopRules | null): { metric: string; band: number; setBy: SetBy | null }[] {
  if (!rules) return [];
  return Object.entries(rules.stability_band)
    .filter(([, item]) => item.set_by !== null && typeof item.value === "number")
    .map(([metric, item]) => ({ metric, band: item.value as number, setBy: item.set_by }));
}

/** ADR-109 d.11: no run before the stability bands are set. */
export function bandsAreSet(rules: ShopRules | null): boolean {
  return setBands(rules).length > 0;
}
