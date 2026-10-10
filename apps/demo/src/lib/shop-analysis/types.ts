/**
 * The shop diagnosis report as `GET /v1/demo/analysis` returns it — the
 * ADR-108 `report.json` (`ShopDiagnosis.to_dict()` in
 * `backend/src/juli_backend/services/shop_diagnosis/report.py`), wrapped as
 * `{ as_of, built_at, ranking, report }` (D21: the report JSON is the API contract).
 *
 * Only the stored fields cross the wire: every rate (CTR, CTOR, AOV, Tỷ lệ
 * thêm vào giỏ hàng, …) is a Python property and is recomputed client-side
 * from the counts (`derive.ts`), exactly as `channels.Counts` computes it.
 * All counts are DAILY AVERAGES over their 30-day window. Dates are ISO
 * `YYYY-MM-DD`; enums arrive as their Vietnamese/string values.
 *
 * Every field the view reads defensively is typed optional, so an older or
 * newer report renders what it has instead of crashing.
 */

export type ChannelKey =
  | "product_card"
  | "shop_tab"
  | "seller_video"
  | "seller_live"
  | "affiliate"
  | "affiliate_video"
  | "affiliate_live"
  | "total";

export type ConfidenceLabel = "Rõ" | "Tham khảo" | "Chưa đủ dữ liệu";

export type FactorKey = "impressions" | "ctr" | "ctor" | "aov";

export interface Counts {
  impressions: number;
  clicks: number;
  /** `null` where TikTok does not report add-to-carts (Tab Cửa hàng). */
  add_to_cart: number | null;
  /** `null` where the channel has no orders (affiliate Video/LIVE branches). */
  sku_orders: number | null;
  gmv: number;
  /** Tab Cửa hàng's SKU orders are derived as CTOR × clicks. */
  orders_estimated?: boolean;
  orders?: number;
  items_sold?: number;
  refunds?: number;
}

export interface FactorChange {
  factor: FactorKey;
  prior: number | null;
  last: number | null;
  /** ₫ per day of the GMV change carried by this factor. */
  contribution: number | null;
  confidence: ConfidenceLabel | null;
}

export interface FunnelComparison {
  prior: Counts;
  last: Counts;
  orders_prior?: number | null;
  orders_last?: number | null;
  factors: FactorChange[];
  gmv_confidence?: ConfidenceLabel | null;
  add_to_cart_rate_confidence?: ConfidenceLabel | null;
  orders_per_cart_confidence?: ConfidenceLabel | null;
}

export interface ChannelRow {
  channel: ChannelKey;
  comparison: FunnelComparison;
  share_of_change: number | null;
  additive: boolean;
  tags?: string[];
}

export interface GroupRow {
  label: string;
  channels: ChannelKey[];
  comparison: FunnelComparison;
  share_of_change: number | null;
}

export interface RollingPoint {
  day: string;
  impressions: number | null;
  ctr: number | null;
  ctor: number | null;
  aov: number | null;
}

export interface ChannelTimeline {
  channel: ChannelKey;
  points: RollingPoint[];
}

export interface Band {
  /** "Flash sale" | "Giảm giá sản phẩm" | "Voucher" | … (PromoKind values). */
  kind: string;
  title: string;
  first: string;
  last: string;
  days_prior: number;
  days_last: number;
  /** Products in the promotion (fast track P12); null for vouchers / unknown lists. */
  product_count?: number | null;
}

export interface DayGroupCell {
  group: string;
  days: number;
  sku_orders: number;
  ctor: number | null;
  orders_per_cart: number | null;
  sufficient: boolean;
}

export interface FlashAnalysis {
  /** Share of each day covered by a flash sale, keyed by ISO date. */
  coverage: Record<string, number>;
  /** `[monday ISO date, coverage share]` pairs. */
  weekly: Array<[string, number]>;
  coverage_last: number | null;
  coverage_prior: number | null;
  flash_days_last: number;
  flash_days_prior: number;
  true_depth: number | null;
  list_depth: number | null;
  cells: DayGroupCell[];
  flags: string[];
  unattributed?: number;
}

export interface Voucher {
  title: string;
  threshold: number | null;
  amount_off?: number | null;
  percent_off?: number | null;
}

export interface VoucherAnalysis {
  voucher: Voucher;
  voucher_class: string;
  specific_products: boolean;
  first: string;
  last: string;
  discount_share: number | null;
  near_threshold_share: number | null;
  above_before: number | null;
  above_after: number | null;
  redemptions_upper: number;
  cost_upper: number;
  overlaps_flash: boolean;
}

export interface VoucherSummary {
  yardstick: { common_price: number; closing_cut: number; sample: number } | null;
  live: VoucherAnalysis[];
  /** `[month, class label, count]` triples. */
  older_by_month: Array<[string, string, number]>;
}

export interface Conclusion {
  verdict: string;
  factor?: FactorKey | null;
  side?: string | null;
  gmv_change_share?: number | null;
  headline: string;
  look_next: string;
}

export interface OrderDiscountShare {
  items: number;
  platform_share: number | null;
  seller_share: number | null;
}

export interface Appearance {
  kind: string;
  title: string;
  day: string;
  impressions: number | null;
  orders: number | null;
}

export interface Appearances {
  top_live: Appearance[];
  live_without_orders: number;
  top_videos: Appearance[];
  videos_without_orders: number;
}

export interface HeroProfile {
  rank: number;
  product_id: string;
  title: string;
  conclusion: Conclusion;
  total: FunnelComparison;
  self_search: FunnelComparison;
  channels: ChannelRow[];
  affiliate_rows: ChannelRow[];
  /** `{channel: [prior share, last share]}`. */
  gmv_share: Partial<Record<ChannelKey, [number | null, number | null]>>;
  reading: string;
  content_note: string;
  bands: Band[];
  flash: FlashAnalysis;
  discounts_prior?: OrderDiscountShare;
  discounts_last?: OrderDiscountShare;
  appearances?: Appearances;
}

export interface WatchItem {
  product_id: string;
  title: string;
  reason: string;
  gmv_prior: number;
  gmv_last: number;
}

export interface HeroSelection {
  ranking: "60d" | "30d" | string;
  heroes: string[];
  gmv_share: number;
  /** `[product id, "vào top" | "rơi khỏi top"]` pairs. */
  movers: Array<[string, string]>;
  dispersed: boolean;
}

export interface Windows {
  prior_first: string;
  prior_last: string;
  last_first: string;
  last_last: string;
}

export interface ShopDiagnosisReport {
  shop_name: string;
  end: string;
  windows: Windows;
  ranking: string;
  missing_days: string[];
  sale_days: string[];
  total: FunnelComparison;
  channels: ChannelRow[];
  affiliate_rows: ChannelRow[];
  groups: GroupRow[];
  timelines: ChannelTimeline[];
  shop_bands: Band[];
  shop_flash: FlashAnalysis;
  vouchers: VoucherSummary;
  selection: HeroSelection;
  profiles: HeroProfile[];
  rest_total?: FunnelComparison;
  rest_self_search?: FunnelComparison;
  rest_conclusion?: Conclusion;
  watch: WatchItem[];
  titles: Record<string, string>;
  orders_present: boolean;
  /** Fast track P12 (additive, `fasttrack/contracts/p12-phan-tich.md`): GMV per present day of the 60, all channels. */
  daily_gmv?: Record<string, number>;
  /** P12: product id → seller SKU. */
  seller_skus?: Record<string, string>;
  /** P12: the products' promotions over the 60 days. */
  promo_products?: PromoProduct[];
}

/** P12 `promo_products[]` (backend `promotions.PromoProduct`). */
export interface PromoProduct {
  product_id: string;
  /** PromoKind value: "Flash sale" | "Giảm giá sản phẩm" | "Mua nhiều giảm nhiều". */
  kind: string;
  /** Days a promotion covered at least half the day. */
  days: number;
  /** Median true depth (flash) or depth vs list price (discount), as a share. */
  depth: number | null;
  /** Mean daily GMV (all channels) on promotion days / on the other days. */
  gmv_in: number | null;
  gmv_out: number | null;
}

export type HeroRanking = "60d" | "30d";

/** The `GET /v1/demo/analysis[?ranking=60d|30d]` body (P7-A). */
export interface ShopAnalysisEnvelope {
  as_of: string;
  built_at: string;
  /** Which hero ranking the report was built with; default "60d". */
  ranking?: HeroRanking;
  report: ShopDiagnosisReport;
}
