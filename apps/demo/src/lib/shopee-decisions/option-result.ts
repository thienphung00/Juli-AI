// P98 / ADR-122 d.5: the wire shape of one option result — mirrors
// backend/src/juli_backend/services/shopee_builder/engine/contract.py WIRE_KEYS exactly.
// Money and counts are numbers (VND / count); pct are percent numbers (3.5 = +3,5 %); null = unknown.

export type Driver = "views" | "ctr" | "ctor" | "aov";
export type Basis = "measured" | "product_history" | "shop" | "prior" | "not_estimable";

export interface DeltaMoney {
  readonly value: number | null;
  readonly pct: number | null;
}

export interface DeltaProfit extends DeltaMoney {
  readonly low: number | null;
  readonly high: number | null;
}

export interface FunnelColumn {
  readonly views: number | null;
  readonly ctr: number | null;
  readonly ctor: number | null;
  readonly orders: number;
  readonly aov: number | null;
  readonly gmv: number;
  readonly profit: number | null;
  readonly by_source: Readonly<Record<string, Readonly<Record<string, number | null>>>>;
}

/** P100 B.15: an edit of a running Dịch vụ hiển thị campaign — the campaign's own CPA facts (`*.now` today, `*.after` with the edit; null = chưa ước tính được). */
export interface AdsEditFacts {
  readonly lever: "budget" | "roas" | "add_product" | "remove_product" | string;
  readonly campaign: string;
  readonly days: number;
  readonly spend_basis: string;
  readonly spend_text: string;
  readonly spend: { readonly now: number | null; readonly after: number | null };
  readonly orders: { readonly now: number | null; readonly after: number | null };
  readonly cpa: { readonly now: number | null; readonly after: number | null };
  readonly break_even_cpa: number | null;
  readonly verdict: { readonly now: "co_lai" | "lo" | null; readonly after: "co_lai" | "lo" | null };
  readonly verdict_text: { readonly now: string | null; readonly after: string | null };
  readonly profit_after_ads: { readonly now: number | null; readonly after: number | null };
  readonly roas_shopee: { readonly now: number | null; readonly after: number | null };
  readonly incremental: { readonly share: number | null; readonly orders_all: number | null; readonly orders_extra: number | null };
  readonly cancel_rate_pct: number | null;
}

export interface OptionResult {
  readonly kind: string;
  readonly label: string;
  readonly days: number;
  readonly horizon: "duration" | "first_30_days";
  readonly drivers: readonly Driver[];
  readonly estimable: boolean;
  readonly basis: Basis;
  readonly basis_weak: boolean;
  readonly delta: {
    readonly profit: DeltaProfit | null;
    readonly gmv: DeltaMoney;
    readonly orders: DeltaMoney & { readonly note: string | null };
  };
  readonly build_up: readonly { readonly key: string; readonly amount: number; readonly text: string }[];
  readonly drivers_pct: readonly { readonly metric: Driver; readonly label: string; readonly pct: number | null }[];
  readonly cost: {
    readonly total: number;
    readonly break_even_orders: number | null;
    readonly break_even_aov: number | null;
    readonly text: string;
  };
  readonly after: {
    readonly days: number;
    readonly label: string;
    readonly gmv_before: number;
    readonly gmv_after: number | null;
    readonly profit_before: number | null;
    readonly profit_after: number | null;
  };
  /** P99b: the same Δ rescaled to 30 days. P100 B.6: no longer shown anywhere in the UI; the server still sorts by it (the comparison order), so the field stays on the wire. */
  readonly per_30d: { readonly profit: number | null; readonly gmv: number | null; readonly orders: number | null; readonly secondary?: boolean; readonly label?: string };
  /** P100-C (B.4): ROI = ΔGMV ÷ chi phí (incremental); value/text null without a cost or an estimate. Optional for results stored before P100-C. */
  readonly roi?: { readonly value: number | null; readonly text: string | null };
  /** P100-C (B.6): profit ÷ GMV before / after (percent numbers) and the shift in points. */
  readonly margin?: { readonly before_pct: number | null; readonly after_pct: number | null; readonly shift_pts: number | null };
  readonly detail: {
    readonly before: FunnelColumn;
    readonly low: FunnelColumn | null;
    readonly likely: FunnelColumn | null;
    readonly high: FunnelColumn | null;
  };
  readonly notes: readonly string[];
  /** P100 B.15: Ads edits only (null / absent for every other kind and for results stored before). */
  readonly ads?: AdsEditFacts | null;
}
