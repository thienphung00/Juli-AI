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
  readonly per_30d: { readonly profit: number | null; readonly gmv: number | null; readonly orders: number | null };
  readonly detail: {
    readonly before: FunnelColumn;
    readonly low: FunnelColumn | null;
    readonly likely: FunnelColumn | null;
    readonly high: FunnelColumn | null;
  };
  readonly notes: readonly string[];
}
