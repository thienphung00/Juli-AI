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
  /** The raw value: a text ("Shopee Video" · "Facebook" · "TikTok" …) or the Connector's legacy `traffic_type` code ("0" / "1" / "2"). */
  readonly channel: string;
  /** P100: the seller's word for `channel` ("1" -> "Trong Shopee (Video/Live)"). Older payloads lack it. */
  readonly channel_label?: string | null;
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
  /** The creator's buyers in the period (P96: Juli Connector's KOL analytics page). */
  readonly kol_buyers?: N;
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
  /** P100: "5" -> "Chiến dịch mở"; text as it came. */
  readonly campaign_type_label?: string | null;
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

export interface KolOption {
  readonly value: string | null;
  readonly label: string | null;
}

export interface KolReport {
  readonly window: { readonly start?: string; readonly end?: string; readonly days?: number; readonly [k: string]: unknown };
  readonly rows: readonly KolRow[];
  /** Of the rows after the filters (before `limit`). */
  readonly totals: KolTotals;
  /** Always built from ALL rows, so a filter never hides its own options. */
  readonly filters: {
    readonly channels: readonly string[];
    /** P100: the same channels with their labels. */
    readonly channel_options?: readonly KolOption[];
    readonly campaign_types?: readonly KolOption[];
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
  /** P100 `GET {base}/kols/compare?group=`; absent on hosts without it. */
  compare?(group: KolCompareGroup, window?: WindowQuery): Promise<KolCompareReport>;
}

// ── So sánh (P100): GET {base}/kols/compare?group=channel|campaign_type|kol ──

export type KolCompareGroup = "channel" | "campaign_type" | "kol";

export interface KolBasis {
  readonly key: string;
  /** "Theo báo cáo chuyển đổi KOL" · "Theo nguồn lưu lượng" · "Theo báo cáo quảng cáo (đơn đã đặt)". */
  readonly label: string;
}

/** One group: the sum of its KOL × sản phẩm × kênh rows. Money in VND; `*_pct` in percent points. */
export interface KolCompareRow {
  readonly key: string;
  readonly label: string;
  readonly orders: number;
  readonly units: number;
  readonly gmv: number;
  /** Commission Shopee charges (incl. its 8 %). */
  readonly cost: number;
  readonly cost_pct_gmv: N;
  /** null: a sample was sent whose cost cannot be computed. */
  readonly sample_cost: N;
  readonly net_profit: number;
  readonly profit_after_samples: number;
  readonly profit_orders: number;
  readonly profit_per_order: N;
  /** A fraction. */
  readonly roi_incl_samples: N;
  readonly kols: number;
  readonly products: number;
  readonly share_gmv_pct: N;
  readonly low_data: boolean;
  readonly low_data_label: string | null;
}

/** One row of the stream strip; a figure no source gives is null with `reason` / `profit_reason`. */
export interface KolStreamRow {
  readonly key: "affiliate" | "ads" | "organic";
  readonly label: string;
  readonly gmv: N;
  readonly orders: N;
  readonly basis: KolBasis;
  readonly cost: N;
  readonly cost_basis: KolBasis | null;
  readonly cost_pct_gmv: N;
  readonly profit_after_cost: N;
  readonly profit_reason: string | null;
  readonly reason: string | null;
  readonly note: string | null;
  /** Affiliate only: the conversion report's own GMV / orders, which the cost % stands on. */
  readonly conversion_report?: { readonly gmv: N; readonly orders: number };
}

export interface KolCompareReport {
  readonly window: { readonly from?: string; readonly to?: string; readonly days?: number; readonly [k: string]: unknown };
  readonly group: KolCompareGroup;
  readonly group_label: string;
  readonly rows: readonly KolCompareRow[];
  readonly total: KolCompareRow;
  readonly streams: {
    readonly rows: readonly KolStreamRow[];
    readonly shop_gmv: N;
    readonly shop_orders: number | null;
    readonly note: string;
  };
  readonly basis: KolBasis;
  readonly labels: {
    readonly cost: string;
    readonly net_profit: string;
    readonly profit_per_order: string;
    readonly roi_formula: string;
    readonly low_data: string;
    readonly low_data_threshold: number;
    readonly share_gmv: string;
  };
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
