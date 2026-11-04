import type { WindowQuery } from "../shopee-analytics/client";
import type { N } from "../shopee-decisions/types";

/**
 * KOL × sản phẩm × kênh (P91 D-9 / D-11), the shapes the backend sends:
 *   GET {shopee analytics base}/kols                      -> {@link KolReport}
 *   GET {shopee analytics base}/products/{item_id}/kols    -> {@link KolProductReport}
 *   card `affiliate_sample` / `affiliate_invite`           -> `kol` on the card and on each version ({@link KolBlock})
 *   the Mẫu KOL sheet rides on the shop-inputs template / preview / apply (`shop-inputs/types.ts`)
 */

export type KolCardKind = "affiliate_sample" | "affiliate_invite";

export type KolSort = "net_profit" | "orders" | "gmv" | "roi_incl_samples" | "commission";

/** The open Gửi mẫu / Mời KOL card of a KOL (`attach_kol_cards`). */
export interface KolCardRef {
  readonly id: string;
  readonly code: string;
  readonly change_kind: KolCardKind;
  readonly kind_label: string;
  readonly title: string;
  readonly product_queue: number | null;
  readonly item_id: string | null;
}

export interface KolRow {
  /** Hashed affiliate key (the raw id is never stored). */
  readonly kol_key: string;
  readonly handle: string;
  /** "Shopee Video" · "Facebook" · "TikTok" … */
  readonly channel: string;
  readonly item_id: string;
  readonly product_name: string;
  readonly orders: number;
  readonly units: number;
  readonly gmv: number;
  /** Always null: the clicks of the pair are not known; `kol_clicks` is the creator's. */
  readonly clicks: number | null;
  /** The creator's clicks in the Shopee export (all products). */
  readonly kol_clicks: N;
  /** The creator's conversion in the export, a fraction. */
  readonly kol_conversion: N;
  readonly commission: number;
  /** Commission ÷ base, a fraction. */
  readonly commission_rate: N;
  readonly commission_sources: Readonly<Record<string, number>>;
  readonly net_profit: number;
  readonly profit_orders: number;
  readonly unknown_lines: number;
  readonly sample_qty: number;
  /** null: samples were sent but their cost cannot be computed. */
  readonly sample_cost: N;
  readonly sample_cost_basis: string | null;
  readonly profit_after_samples: number;
  /** (net − sample) ÷ (commission + sample), a fraction; null when there is nothing to divide by. */
  readonly roi_incl_samples: N;
  /** The `ROI` of Shopee's KOL export, as a number; never recomputed. */
  readonly roi_shopee: N;
  readonly payback_orders: number | null;
  readonly pair_orders: number;
  /** Fewer than `labels.low_data_threshold` orders for the KOL × product pair. */
  readonly low_data: boolean;
  readonly low_data_label: string | null;
  readonly mcn: boolean | null;
  readonly campaign_type: string | null;
  readonly card: KolCardRef | null;
}

export interface KolTotals {
  readonly rows: number;
  readonly kols: number;
  readonly orders: number;
  readonly units: number;
  readonly gmv: number;
  readonly commission: number;
  readonly net_profit: number;
  readonly sample_cost: N;
  readonly profit_after_samples: number;
  readonly roi_incl_samples: N;
}

export interface KolLabels {
  readonly roi_self: string;
  readonly roi_shopee: string;
  readonly low_data: string;
  readonly roi_formula: string;
  readonly roi_shopee_note: string;
  readonly sample_cost: string;
  readonly commission: string;
  readonly low_data_threshold: number;
}

export interface KolReport {
  readonly window: { readonly start?: string; readonly end?: string; readonly days?: number; readonly [k: string]: unknown };
  readonly rows: readonly KolRow[];
  /** Of the rows after the filters (before `limit`). */
  readonly totals: KolTotals;
  /** Always built from ALL rows, so a filter never hides its own options. */
  readonly filters: {
    readonly channels: readonly string[];
    readonly products: readonly { readonly item_id: string; readonly name: string }[];
    readonly kols: readonly { readonly kol_key: string; readonly handle: string }[];
  };
  readonly applied: { readonly channel: string | null; readonly item_id: string | null; readonly kol: string | null; readonly sort: KolSort };
  readonly labels: KolLabels;
  readonly data_quality: {
    readonly untagged_affiliate_lines: number;
    readonly lines_without_commission: number;
    readonly partner_export: unknown;
  };
  readonly order_basis: { readonly key: string; readonly label: string };
}

/** Sản phẩm › Tiếp thị liên kết: the same body plus the product and its commission now. */
export interface KolProductReport extends KolReport {
  readonly product: {
    readonly item_id: string;
    readonly name: string | null;
    /** Fraction; null when the product's rate is not known. */
    readonly commission_rate: N;
    readonly commission_rate_source: string | null;
    readonly affiliate_orders: number;
  };
}

export interface KolQuery {
  readonly window?: WindowQuery;
  readonly channel?: string | null;
  readonly itemId?: string | null;
  readonly kol?: string | null;
  readonly sort?: KolSort;
  readonly limit?: number;
}

export interface KolApi {
  report(query?: KolQuery): Promise<KolReport>;
  productReport(itemId: string, window?: WindowQuery): Promise<KolProductReport>;
}

/**
 * The `kol` block of a Gửi mẫu / Mời KOL card and of each of its versions (`kol_cards.build_kol_card`).
 * `expected` is at the middle of the orders (P50) plus the P10 / P90 of the orders; the profit after
 * samples has its own range, the ROI and the payback are single numbers.
 */
export interface KolBlock {
  readonly kol_key: string;
  readonly handle: string;
  readonly channel: string;
  readonly invite: boolean;
  readonly roi_shopee: N;
  readonly product: { readonly item_id: string; readonly name: string };
  /** Mẫu gửi; 0 for an invitation. */
  readonly qty: number;
  readonly commission_pct: number;
  readonly commission_pct_current: N;
  readonly commission_source: string | null;
  /** null for an invitation. */
  readonly sample: {
    readonly cost: number;
    readonly unit_cogs: number;
    readonly unit_packaging: number;
    readonly ship_fee: number;
    readonly ship_source: string;
    readonly cogs_source: string;
    readonly label: string;
  } | null;
  readonly expected: {
    readonly orders: { readonly p10: number; readonly p50: number; readonly p90: number };
    readonly gmv: number;
    readonly commission: number;
    readonly net_profit: number;
    readonly profit_after_sample: number;
    /** [low, high] of the profit after samples. */
    readonly profit_after_sample_range: readonly [number, number];
    readonly roi_incl_samples: N;
    readonly payback_orders: number | null;
    readonly net_per_order: number;
  };
  readonly low_data: boolean;
  readonly low_data_label: string | null;
  readonly pair_orders: number;
  readonly orders_threshold: number;
  readonly shrinkage: unknown;
  /** The products this creator could be pitched, best expected profit first (the `item_id` what-if choice). */
  readonly choices: readonly { readonly value: string; readonly label: string; readonly orders_p50: number; readonly profit_p50: number; readonly selected: boolean }[];
  readonly measurement: {
    readonly kind: "kol_pair";
    readonly metric: string;
    readonly kol_key: string;
    readonly item_id: string;
    readonly send_date: string | null;
    readonly baseline_days: number;
    readonly note: string;
  };
}
