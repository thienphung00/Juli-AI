/**
 * One ADR-109 d.5 ranking table as `GET /v1/demo/analysis/rankings?stream=&metric=`
 * returns it (fast track P8-A): `{ as_of, built_at, stream, metric, ranking }`,
 * where `ranking` is the payload of
 * `backend/src/juli_backend/services/shop_diagnosis/rankings.py` (`_payload` +
 * `_table`). Every `gmv_per_day` is ₫ per day of the stream's GMV change carried
 * by that row's change in the metric; listed rows + the three closing rows add up
 * to `stream_factor_gmv` (the cell's GMV figure).
 */

/** Backend `Channel` values of the four ranked streams. */
export type RankedStream = "product_card" | "shop_tab" | "seller_video" | "seller_live";

/** Backend `rankings.Metric` values. */
export type RankedMetric =
  | "impressions"
  | "ctr"
  | "ctor"
  | "add_to_cart_rate"
  | "orders_per_cart"
  | "aov";

export type RowKind = "product" | "live_session" | "video";

export interface RankingRow {
  /** Product id, LIVE session id or video id. */
  id: string;
  /** Product title; LIVE: "<title> · dd/mm/yyyy"; video title. */
  name: string;
  gmv_per_day: number;
  confidence: "Rõ" | "Tham khảo" | null;
  /** The metric before → after (content rows: the stream's prior value → the row's). */
  prior: number | null;
  last: number | null;
  /** The quantity behind the metric (lượt hiển thị / lượt bấm / đơn hàng SKU), window totals. */
  quantity_prior: number | null;
  quantity_last: number;
  /** LIVE sessions and videos: ISO day. */
  date?: string;
  method?: string;
  /** CTOR on Thẻ sản phẩm: the share carried by each of its two steps. */
  steps?: Partial<Record<"add_to_cart_rate" | "orders_per_cart", number>>;
  /** Product rows: the seller SKU (fast track P12, additive). */
  seller_sku?: string | null;
  /** LIVE / video rows: the product ids it featured (fast track P12, additive). */
  product_ids?: string[];
}

export interface ClosingRow {
  label: string;
  count?: number;
  gmv_per_day: number;
}

export interface RankingPayload {
  stream: RankedStream;
  stream_label?: string;
  metric: RankedMetric;
  metric_label?: string;
  row_kind: RowKind;
  windows?: { prior: [string, string]; last: [string, string] };
  unit?: string;
  stream_prior: number | null;
  stream_last: number | null;
  stream_gmv_prior?: number;
  stream_gmv_last?: number;
  stream_gmv_change?: number;
  stream_factor_gmv: number;
  method?: string;
  orders_estimated?: boolean;
  down: RankingRow[];
  up: RankingRow[];
  closing: { few: ClosingRow; others: ClosingRow; mix: ClosingRow };
}

export interface RankingEnvelope {
  as_of: string;
  built_at: string;
  stream: RankedStream;
  metric: RankedMetric;
  ranking: RankingPayload;
}

/** Resolves a table, `null` when none is stored (404); rejects on failure. */
export type RankingLoader = (stream: RankedStream, metric: RankedMetric) => Promise<RankingEnvelope | null>;
