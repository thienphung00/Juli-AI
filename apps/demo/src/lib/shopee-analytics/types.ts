/**
 * Payload shapes of the Shopee shop read APIs (`GET /v1/demo/shopee/*` for the seller,
 * `GET /v1/ops/shops/{id}/shopee/analytics/*` for staff; backend module
 * `services/shopee_analytics`, contract `fasttrack/contracts/p90-metrics.md`).
 *
 * Money is VND, ratios (ctr, ctor) are fractions, every `*_pct` is percent points. `null` is
 * "not known", never 0. The payloads carry no buyer field: money after voucher is
 * `net_revenue` (there is no `buyer_paid`; the order list says `paid_amount`).
 */

export type N = number | null;

export interface WindowJson {
  readonly from: string;
  readonly to: string;
  readonly days: number;
}

export interface Warning {
  readonly code: string;
  readonly message: string;
}

export interface Kpi {
  readonly value: N;
  readonly previous: N;
  readonly change_pct: N;
}

/** P100 B.5: the profit of the orders whose costs are known, with its coverage. */
export interface ShopProfitFigure {
  readonly profit: N;
  readonly margin_pct: N;
  readonly orders: number;
  readonly gmv: N;
  readonly gmv_share_pct: N;
  readonly label: string;
}

export interface MarginKpi {
  readonly value: N;
  readonly previous: N;
  readonly label: string | null;
}

export interface FlowRow {
  readonly key: string;
  readonly label: string;
  readonly is_residual: boolean;
  readonly views: N;
  readonly clicks: N;
  readonly orders: number;
  readonly gmv: N;
  readonly ctr: N;
  readonly ctor: N;
  readonly aov: N;
  readonly share_pct: N;
  readonly identity_gmv?: N;
  readonly identity_ok?: boolean;
  readonly gmv_previous?: N;
  readonly gmv_change_pct?: N;
}

export interface FlowTable {
  readonly rows: readonly FlowRow[];
  readonly total_gmv: N;
  readonly total_orders: N;
  readonly gmv_sum: N;
  readonly orders_sum: number;
  readonly adds_up: boolean;
  readonly has_residual: boolean;
}

export interface CardChild {
  readonly key: string;
  readonly label: string;
  readonly views: N;
  readonly clicks: N;
  readonly orders: number;
  readonly gmv: N;
}

export interface OverviewFlows extends Partial<FlowTable> {
  readonly available: boolean;
  readonly basis?: string;
  readonly the_san_pham_children?: {
    readonly rows: readonly CardChild[];
    readonly gmv_sum: N;
    readonly parent_gmv: N;
    readonly note: string;
  };
  readonly chain?: {
    readonly views: N;
    readonly clicks: N;
    readonly orders: N;
    readonly ctr: N;
    readonly ctor: N;
    readonly aov: N;
    readonly gmv: N;
    readonly identity_gmv: N;
    readonly identity_ok: boolean;
    readonly note: string;
  };
}

export interface Cell {
  readonly orders: number;
  readonly gmv: N;
  readonly net_revenue: N;
  readonly contribution: N;
  readonly profit: N;
  readonly margin_pct: N;
  readonly aov: N;
  readonly orders_missing_profit: number;
  readonly orders_excluded: number;
}

export interface LeverRow extends Cell {
  readonly key: string;
  readonly label: string;
  readonly share_pct?: N;
}

export interface CostCoverage {
  readonly net_revenue: number;
  readonly real_pct: N;
  readonly assumed_pct: N;
  readonly unknown_pct: N;
  readonly packaging_assumed_pct: N;
  readonly label: string;
}

export interface AdsLabel {
  readonly key: string;
  readonly label: string;
}

export interface ProfitBlock {
  /** P100 B.5: the one shop profit (known-cost orders), the same figure as Sản phẩm and Kế hoạch. */
  readonly profit_vnd: N;
  /** "trên N đơn có chi phí, X % GMV" */
  readonly coverage_label?: string;
  /** P100 B.5: the bridge on the known-cost basis; its lines add up exactly to `profit`. */
  readonly bridge?: {
    readonly product_profit: N;
    readonly ads_unattributed: N;
    readonly other_marketing: N;
    readonly profit: N;
    readonly ads_charged: N;
    readonly ads_total: N;
    readonly ads_label: string;
  };
  readonly known_cost_orders?: number;
  readonly known_cost_gmv_share_pct?: N;
  readonly profit_on_covered_vnd: N;
  readonly margin_pct: N;
  readonly margin_basis: string;
  readonly contribution_before_ads: N;
  readonly net_revenue: N;
  readonly orders: number;
  readonly cost_coverage: CostCoverage;
  readonly assumed_cost_share_pct: N;
  readonly assumed_cost_label: string;
  readonly profit_is_partial: boolean;
  readonly ad_spend: {
    readonly total: N;
    readonly by_product: N;
    readonly unattributed: N;
    readonly zero_revenue_campaigns: N;
    readonly consistent: boolean;
    readonly unattributed_label: string;
  };
  readonly other_marketing_costs: N;
  readonly break_even_roas: N;
  readonly gmv_reconciliation: {
    readonly line_gmv: N;
    readonly shopee_gmv: N;
    readonly gap: N;
    readonly gap_pct: N;
    readonly warn: boolean;
  };
  readonly missing: Readonly<Record<string, number>>;
}

export interface AdsBlock {
  readonly basis: AdsLabel;
  readonly note: string;
  readonly in_which: string;
  readonly spend: N;
  readonly gmv_placed: N;
  readonly orders_placed: N;
  readonly roas: N;
  readonly spend_per_day: N;
  readonly allocation: { readonly basis: string; readonly label: string };
}

export interface FiveNumbers {
  readonly discount: {
    readonly vnd_before: N;
    readonly vnd_after: N;
    readonly pct_before: N;
    readonly pct_after: N;
  };
  readonly extra_revenue_per_extra_spend: {
    readonly extra_revenue: N;
    readonly extra_spend: N;
    readonly per_vnd: N;
    readonly pct: N;
    readonly status: string;
    readonly below_one: boolean;
  };
  readonly margin: {
    readonly profit_before: N;
    readonly profit_after: N;
    readonly pct_before: N;
    readonly pct_after: N;
    readonly is_partial: boolean;
    readonly cost_coverage_pct: N;
  };
  readonly orders: { readonly before: N; readonly after: N; readonly change_pct: N };
  readonly aov: { readonly before: N; readonly after: N; readonly change_pct: N };
  readonly spend_cap: {
    readonly spend_per_day: N;
    readonly cap: N;
    readonly remaining: N;
    readonly used_pct: N;
    readonly over_cap: boolean;
  } | null;
  readonly chi_definition: string;
  readonly comparison: { readonly available: boolean; readonly reason: string | null };
}

export interface DataCoverage {
  readonly basis?: string;
  readonly days_covered: number;
}

export interface Overview {
  readonly platform: "shopee";
  readonly order_basis: AdsLabel;
  readonly period: { readonly window: WindowJson; readonly previous: WindowJson; readonly kind?: string };
  readonly data: {
    readonly shop_totals: DataCoverage;
    readonly traffic: DataCoverage;
    readonly ads_daily: { readonly days_covered: number };
    readonly order_lines: {
      readonly lines: number;
      readonly days_with_orders: number;
      readonly window_days: number;
      readonly covers_window: boolean;
    };
    readonly product_flows?: { readonly source: string | null; readonly trang_shop_split: boolean };
  };
  readonly warnings: readonly Warning[];
  readonly kpi_strip: {
    readonly gmv: Kpi;
    readonly views: Kpi;
    readonly ctr: Kpi;
    readonly ctor: Kpi;
    readonly aov: Kpi;
    readonly orders: Kpi;
    /** P100 B.6: Tổng lợi nhuận, the one shop profit with its coverage line. */
    readonly profit?: Kpi & { readonly label: string };
    readonly margin_pct: MarginKpi;
  };
  /** P100 B.5: the one shop profit of the window (absent before P100). */
  readonly shop_profit?: ShopProfitFigure;
  readonly gmv: {
    readonly shopee_gmv: N;
    readonly shopee_orders: N;
    readonly aov_gmv: N;
    readonly aov_seller_centre: N;
    readonly aov_note: string;
    readonly line_gmv: N;
    readonly line_orders: number;
    /** P92 B-1: the part of the GMV from excluded listings (still inside `shopee_gmv`); absent before P92. */
    readonly excluded_gmv?: N;
  };
  readonly flows: OverviewFlows;
  readonly levers: {
    readonly rows: readonly LeverRow[];
    readonly gmv_sum: N;
    readonly gmv_total: N;
    readonly adds_up: boolean;
    readonly note: string;
  };
  readonly five_numbers: FiveNumbers;
  readonly profit: ProfitBlock;
  readonly ads: AdsBlock;
  readonly targets: Readonly<Record<string, N>>;
}

export interface ProductFlows extends FlowTable {
  readonly trang_shop_available: boolean;
}

export interface ProductAds {
  readonly basis: AdsLabel;
  readonly note: string;
  readonly spend: N;
  readonly gmv_placed: N;
  readonly direct_gmv_placed: N;
  readonly roas_broad: N;
  readonly roas_direct: N;
  readonly break_even_roas: N;
  readonly below_break_even: boolean | null;
}

export interface MatrixProduct {
  readonly product_id: string;
  readonly name: string;
  readonly gmv: N;
  readonly gmv_basis: string;
  readonly orders: N;
  readonly line_gmv: N;
  readonly line_orders: number;
  /** P92 B-9: selling price per unit (min-max), list price, and the basis of the biên. */
  readonly price_min?: N;
  readonly price_max?: N;
  readonly list_price?: N;
  readonly price_basis?: string | null;
  readonly margin_basis?: "theo đơn thực tế" | "ước tính" | "chưa tính" | string;
  readonly profit: {
    readonly profit: N;
    readonly margin_pct: N;
    readonly contribution: N;
    readonly net_revenue: N;
    readonly ad_spend: N;
    readonly break_even_roas: N;
    readonly cost_coverage_pct: N;
    readonly assumed_cost: boolean;
  } | null;
  readonly flows: ProductFlows | null;
  /** P100 A.6: the product's own funnel from Shopee's product table (the Sản phẩm + luồng source). */
  readonly traffic?: ProductTraffic | null;
  readonly levers: readonly LeverRow[];
  readonly ads: ProductAds;
  /** Optional: the Quyết định card the product has, when the card pipeline provides one. */
  readonly card?: CardRef | null;
}

export interface ProductTraffic {
  readonly views: N;
  readonly clicks: N;
  readonly orders: number;
  readonly source: string;
  readonly label: string;
}

export interface CardRef {
  readonly id: string;
  /** ads · promotion · voucher · sale · combo · affiliate · mega_sale. */
  readonly family?: string;
  readonly title?: string;
  readonly at_stake_per_month?: N;
}

/** An active listing with no order in the window (P92 B-9). */
export interface IdleProduct {
  readonly product_id: string;
  readonly name: string;
  readonly price_min?: N;
  readonly price_max?: N;
  readonly list_price?: N;
  readonly margin_basis?: string;
}

export interface Matrix {
  readonly idle_products?: readonly IdleProduct[];
  readonly platform: "shopee";
  readonly window: WindowJson;
  readonly sort: string;
  readonly products: readonly MatrixProduct[];
  readonly product_count: number;
  readonly ads_basis: AdsLabel;
  readonly sums: { readonly gmv_shopee_products: N; readonly gmv_shop: N; readonly note: string };
}

export interface CriticalReference {
  /** P96b: `previous` = the product's GMV per day in the previous window of the same length. */
  readonly type: "band" | "target" | "floor" | "break_even" | "shop_median" | "previous";
  readonly label: string;
  readonly value: N;
  readonly low?: N;
  readonly high?: N;
  readonly sku?: string;
}

export interface CriticalItem {
  readonly id: string;
  readonly kind: string;
  readonly level: "flow" | "product" | "shop";
  readonly product_id: string | null;
  readonly name: string | null;
  readonly flow: string | null;
  readonly flow_label: string | null;
  readonly kpi: string;
  readonly current: N;
  readonly reference: CriticalReference;
  readonly deviation_pct: N;
  readonly at_stake_per_day: N;
  readonly at_stake_per_month: N;
  readonly money_basis: string;
  readonly cause: { readonly stage: string; readonly text: string };
  readonly change_kinds: readonly string[];
  readonly ranking_link: { readonly kpi: string; readonly src: string; readonly focus: string | null };
  readonly assumed_cost: boolean;
  /** P92 B-9: selling price per unit (min-max), list price, and the basis of the biên. */
  readonly price_min?: N;
  readonly price_max?: N;
  readonly list_price?: N;
  readonly price_basis?: string | null;
  readonly margin_basis?: "theo đơn thực tế" | "ước tính" | "chưa tính" | string;
  readonly margin_pct?: N;
  readonly rank?: number;
  /** Optional: the Quyết định card for this item, when the card pipeline provides one. */
  readonly card?: CardRef | null;
}

export interface Critical {
  readonly platform: "shopee";
  readonly window: WindowJson;
  readonly items: readonly CriticalItem[];
  readonly in_band: readonly CriticalItem[];
  readonly total_at_stake_per_day: N;
  readonly notes: readonly Warning[];
  readonly ranking_rule: string;
}

export interface RankingRow {
  readonly id: string;
  readonly label: string;
  readonly now: N;
  readonly before: N;
  readonly delta: N;
  readonly quantity: { readonly orders_now: N; readonly orders_before: N };
  readonly spend: N;
  readonly confidence: string;
  readonly before_missing: boolean;
  readonly link: { readonly kpi: string; readonly focus: string };
  readonly product_id?: string;
  /** P92 B-9: selling price per unit (min-max), list price, and the basis of the biên. */
  readonly price_min?: N;
  readonly price_max?: N;
  readonly list_price?: N;
  readonly price_basis?: string | null;
  readonly margin_basis?: "theo đơn thực tế" | "ước tính" | "chưa tính" | string;
  readonly margin_pct?: N;
  readonly campaign_key?: string;
  readonly kol_key?: string;
  readonly keyword?: string;
  readonly voucher_cost?: N;
  readonly card?: CardRef | null;
}

export interface ClosingLine {
  readonly label: string;
  readonly delta: N;
  readonly count?: number;
}

export interface RankingView {
  readonly rows: readonly RankingRow[];
  readonly closing: readonly ClosingLine[];
  readonly sum: N;
  readonly cell_delta: N;
}

export interface Ranking {
  readonly platform: "shopee";
  readonly kind: string;
  readonly source: string;
  readonly sub: string | null;
  readonly xep_theo: { readonly key: string; readonly label: string; readonly additive: boolean };
  readonly window: WindowJson;
  readonly previous: WindowJson;
  readonly order_basis: AdsLabel;
  readonly ads_basis: AdsLabel | null;
  readonly ads_note: string | null;
  readonly before_note?: string;
  readonly supported: boolean;
  readonly reason?: string;
  readonly message?: string;
  readonly cell?: { readonly now: N; readonly before: N; readonly delta: N };
  readonly down?: readonly RankingRow[];
  readonly up?: readonly RankingRow[];
  readonly closing?: {
    readonly few: ClosingLine;
    readonly others: ClosingLine;
    readonly mix: ClosingLine;
  };
  readonly views?: { readonly down?: RankingView; readonly up?: RankingView };
  readonly adds_up?: boolean | null;
  readonly adds_up_note?: string | null;
  readonly row_count?: number;
}

export interface WaterfallUnit {
  readonly list: N;
  readonly promo_discount: N;
  readonly shop_voucher: N;
  readonly combo: N;
  readonly net_revenue: N;
  readonly platform_fees: N;
  readonly cogs: N;
  readonly packaging: N;
  readonly commission: N;
  readonly contribution_before_ads: N;
  readonly ads: N;
  readonly profit: N;
  readonly margin_pct: N;
  readonly organic_vs_ads: string;
}

export interface SkuCost {
  readonly sku: string;
  /** The catalogue variation this cost key belongs to (the key may carry a pack: "G500002×3"). */
  readonly variation_id?: string | null;
  /** The plain seller SKU without the pack. */
  readonly base_sku?: string | null;
  readonly units: number;
  readonly list_price: N;
  readonly waterfall_per_unit: WaterfallUnit;
  readonly cost: {
    readonly cogs_per_unit: N;
    readonly cogs_source: string | null;
    readonly packaging: N;
    readonly packaging_source: string | null;
    readonly label: string | null;
  };
  readonly fee: {
    readonly fixed_fee_rate_pct: N;
    readonly rate_source: string | null;
    readonly category: readonly string[] | null;
    readonly platform_fee_rate_pct: N;
    readonly fixed_per_order: N;
  };
  readonly floor: {
    readonly absolute: N;
    readonly operating: N;
    readonly max_discount_pct: N;
    readonly max_discount_amount: N;
    readonly reasons: readonly string[] | Readonly<Record<string, string>> | null;
    readonly net_revenue_per_unit: N;
    readonly breach: "operating" | "absolute" | null;
    readonly margin_target_pct: N;
  } | null;
}

export interface KeywordEntry {
  readonly keyword: string;
  readonly pattern: string | null;
  readonly in_title: boolean | null;
  readonly title_position: number | null;
  readonly within_counted_chars: boolean | null;
  readonly market: {
    readonly volume: N;
    readonly cpc_min: N;
    readonly cpc_max: N;
    readonly difficulty: N;
    readonly collected_on: string;
  } | null;
  readonly ads_placed: { readonly spend: N; readonly gmv: N; readonly orders: N } | null;
}

export interface KeywordsBlock {
  readonly roles: Readonly<Record<string, { readonly label: string; readonly keywords: readonly KeywordEntry[] }>>;
  readonly core: {
    readonly used: number;
    readonly max: number;
    readonly full: boolean;
    readonly in_title: number;
    readonly coverage_pct: N;
  };
  readonly title_counted_chars: number;
}

/** One listing snapshot, as `versions_block` sends it. `cover_url` may be a bare Shopee image id, not a URL. */
export interface ProductVersion {
  readonly captured_at: string;
  readonly title?: string | null;
  readonly title_chars?: number | null;
  readonly list_price?: N;
  readonly current_price?: N;
  readonly cover_url?: string | null;
  readonly image_count?: number | null;
  readonly changes?: readonly unknown[] | null;
  readonly first?: boolean;
  /** Older payloads carried the image list directly. */
  readonly images?: readonly string[] | null;
}

export interface ProductHeader {
  readonly product_id: string;
  readonly title: string | null;
  readonly title_chars: number | null;
  readonly seller_sku: string | null;
  readonly status: string | null;
  readonly category_path: readonly string[] | null;
  /** Image URLs when the backend has private copies; may be empty or hold bare Shopee image ids. */
  readonly images?: readonly string[] | null;
  readonly price: {
    readonly list: N;
    readonly current: N;
    readonly promo_label: string | null;
    readonly source: string | null;
    readonly captured_at: string | null;
  };
  readonly stock: { readonly value: N; readonly age_days: N; readonly stale: boolean };
  readonly reputation: {
    readonly rating: N;
    readonly rating_count: N;
    readonly likes: N;
    readonly sold_total: N;
  };
  readonly variations: readonly {
    readonly variation_id: string | null;
    readonly name: string | null;
    readonly seller_sku: string | null;
    readonly status: string | null;
  }[];
  readonly missing_fields: readonly string[];
  /** Optional: image / title versions when snapshots exist (stepper shown only with 2+). */
  readonly versions?: readonly ProductVersion[] | null;
  readonly group?: string | null;
  readonly group_label?: string | null;
  readonly priority?: string | null;
  readonly days_to_sell_out?: N;
}

export interface ProductKpi {
  readonly gmv: Kpi;
  readonly orders: { readonly value: N; readonly previous: N };
  readonly views: N;
  readonly clicks: N;
  readonly ctr: N;
  readonly ctor: N;
  readonly aov: N;
  readonly profit: MatrixProduct["profit"];
  readonly five_numbers: FiveNumbers;
  readonly basis: { readonly gmv: string; readonly flows: unknown };
}

export interface HistoryEvent {
  readonly at: string;
  readonly type: "card" | "change" | "input" | string;
  readonly title: string;
  readonly detail?: string | null;
  readonly before?: string | null;
  readonly after?: string | null;
}

export interface ProductPage {
  readonly platform: "shopee";
  readonly order_basis: AdsLabel;
  readonly period: {
    readonly selected: string;
    readonly window: WindowJson;
    readonly previous: WindowJson;
  };
  readonly header: ProductHeader;
  readonly kpi_by_period: Readonly<Record<string, ProductKpi>>;
  readonly nguon: MatrixProduct;
  readonly ads: ProductAds;
  readonly cost_and_floor: {
    readonly skus: readonly SkuCost[];
    readonly coverage_label: string;
    readonly floor_note: string;
  };
  readonly keywords: KeywordsBlock;
  /** Optional: Lịch sử events (card events + detected changes) when the backend provides them. */
  readonly history?: readonly HistoryEvent[];
  /** Optional: item_traffic_sources present → the Nguồn tab shows 5 flows. */
  readonly item_traffic_sources?: unknown;
}

/** P100 Tổng quan: `GET …/channel-split` (backend `services/shopee_analytics/channel_split.py`). */
export type ChannelKey = "organic" | "organic_card" | "organic_shop" | "organic_video" | "organic_live" | "ads" | "ads_product" | "ads_shop" | "affiliate";
export type AdBase = "traffic_overview" | "ads_report";

export interface ChannelRow {
  readonly key: ChannelKey;
  readonly parent: ChannelKey | null;
  readonly views: number | null;
  readonly clicks: number | null;
  /** Fractions (0.1 = 10 %). */
  readonly ctr: number | null;
  readonly ctor: number | null;
  readonly aov: number | null;
  readonly gmv: number | null;
  readonly orders: number | null;
  readonly ad_base: AdBase | null;
  /** Share of the total GMV on the traffic-overview base (a fraction); null for ads-report rows. */
  readonly share?: number | null;
  /** The same cells over the previous period of the same length (null = no previous data). */
  readonly prev?: ChannelCells | null;
}

export interface ChannelCells {
  readonly views: number | null;
  readonly clicks: number | null;
  readonly ctr: number | null;
  readonly ctor: number | null;
  readonly aov: number | null;
  readonly gmv: number | null;
  readonly orders: number | null;
  readonly share?: number | null;
}

export interface PlanBar {
  readonly now: number | null;
  readonly goal: number | null;
  /** The pre-plan level of the period and the running cards' Δ inside it (goal = baseline + uplift). */
  readonly baseline?: number | null;
  readonly uplift?: number | null;
  /** Actual >= the pro-rated goal (null without a goal). */
  readonly ahead?: boolean | null;
}

/** Actual against the goal built from the running Kế hoạch cards, over the selected period. */
export interface PlanMonth {
  readonly from: string;
  readonly to: string;
  readonly days: number;
  /** Days elapsed (= `days` when today is not inside the period). */
  readonly day: number;
  /** Fraction of the period elapsed; null unless the period includes today. */
  readonly today_marker: number | null;
  readonly gmv: PlanBar;
  readonly profit: PlanBar;
}

export interface ChannelKpis {
  readonly gmv: number | null;
  readonly orders: number | null;
  readonly profit: number | null;
  readonly cost_total: number | null;
  /** Quảng cáo (ads report), Tiếp thị liên kết, Ưu đãi. */
  readonly cost_ads: number | null;
  readonly cost_affiliate: number | null;
  readonly cost_offers: number | null;
  /** Lợi nhuận ÷ Tổng chi phí, in points (5.4). */
  readonly roi: number | null;
}

export interface ChannelSplit {
  readonly level: "shop" | "product";
  readonly product_id: string | null;
  readonly from: string;
  readonly to: string;
  readonly days?: number;
  /** The running cards' span (earliest start - latest end) at this level; null without a running card. */
  readonly plan_range?: { readonly from: string; readonly to: string } | null;
  readonly updated_at: string | null;
  readonly rows: readonly ChannelRow[];
  readonly kpis: ChannelKpis;
  readonly kpis_prev?: ChannelKpis | null;
  readonly plan?: PlanMonth | null;
}

export type WeakestMetric = "views" | "ctr" | "ctor" | "aov" | "orders";

export interface ChannelProduct {
  readonly product_id: string;
  readonly name: string;
  readonly image_url: string | null;
  readonly gmv: number | null;
  readonly margin: number | null;
  readonly organic_gmv: number | null;
  readonly ads_gmv: number | null;
  readonly affiliate_gmv: number | null;
  readonly weakest_metric: WeakestMetric | null;
}

export interface ChannelProducts {
  readonly from: string;
  readonly to: string;
  readonly products: readonly ChannelProduct[];
}

// ── P100 Phân tích (board B) ─────────────────────────────────────────────────

/** One row of the metric view: the value now and in the previous period of the same length. */
export interface MetricViewRow {
  readonly key: string;
  readonly now: N;
  readonly prev: N;
  /** Relative change (0.12 = +12 %). */
  readonly change: N;
  /** Signed ₫: the GMV gap this metric's change explains (negative = lost). */
  readonly impact: N;
  /** Open Đề xuất cards that move this metric for the row. */
  readonly cards: number;
  readonly ad_base?: string | null;
}

export interface MetricViewProduct extends MetricViewRow {
  readonly product_id: string;
  readonly name: string;
}

export interface MetricView {
  readonly metric: string;
  readonly channel: string | null;
  readonly product_id: string | null;
  readonly from: string;
  readonly to: string;
  readonly days: number;
  readonly prev_from: string;
  readonly prev_to: string;
  /** The whole scope (shop, or the asked luồng / product); margin has none. */
  readonly total: MetricViewRow;
  readonly channels: readonly MetricViewRow[];
  readonly products: readonly MetricViewProduct[];
}

export interface KolSectionRow {
  readonly kol_key: string;
  readonly handle: string;
  readonly channel: string;
  readonly channel_label: string | null;
  readonly item_id: string;
  readonly product_name: string;
  readonly clicks: N;
  readonly orders: number;
  readonly gmv: N;
  readonly commission: N;
  readonly profit: N;
  readonly prev_gmv: N;
  readonly prev_profit: N;
  readonly change: N;
  readonly cards: number;
}

export interface KolSection {
  readonly days: number;
  readonly totals: {
    readonly clicks: N;
    readonly orders: N;
    readonly gmv: N;
    readonly video_gmv: N;
    readonly live_gmv: N;
    readonly other_gmv: N;
  };
  readonly rows: readonly KolSectionRow[];
}
