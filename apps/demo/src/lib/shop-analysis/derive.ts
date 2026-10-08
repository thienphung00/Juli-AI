import type { ChannelKey, ChannelRow, Counts, FactorKey } from "./types";

/**
 * Rates recomputed from a window's counts — the same definitions as the
 * backend's `channels.Counts` properties (ADR-108 decision 1, TikTok's own
 * calculations): a rate over a window is the ratio of the window's totals.
 */

function ratio(numerator: number | null | undefined, denominator: number | null | undefined) {
  if (numerator === null || numerator === undefined) return null;
  if (!denominator || denominator <= 0) return null;
  return numerator / denominator;
}

export const ctr = (c: Counts) => ratio(c.clicks, c.impressions);
export const addToCartRate = (c: Counts) =>
  c.add_to_cart === null ? null : ratio(c.add_to_cart, c.clicks);
export const ctor = (c: Counts) => (c.sku_orders === null ? null : ratio(c.sku_orders, c.clicks));
export const aov = (c: Counts) => (c.sku_orders === null ? null : ratio(c.gmv, c.sku_orders));
export const itemsPerOrder = (c: Counts) => ratio(c.items_sold ?? null, c.orders ?? null);
export const refundShare = (c: Counts) => ratio(c.refunds ?? null, c.gmv);

/** TikTok's Vietnamese channel names (backend `CHANNEL_LABELS`). */
export const CHANNEL_LABELS: Record<ChannelKey, string> = {
  product_card: "Thẻ sản phẩm của người bán",
  shop_tab: "Tab Cửa hàng",
  seller_video: "Video của người bán",
  seller_live: "LIVE của người bán",
  affiliate: "Liên kết",
  affiliate_video: "Video liên kết",
  affiliate_live: "LIVE liên kết",
  total: "Tất cả kênh",
};

/** The five channels of Step 1, in page order. */
export const FIVE_CHANNELS: readonly ChannelKey[] = [
  "product_card",
  "shop_tab",
  "seller_video",
  "seller_live",
  "affiliate",
];

/** Backend `render.SUBTITLES`. */
export const CHANNEL_SUBTITLES: Record<ChannelKey, string> = {
  product_card: "Nhóm khách tự tìm đến · CTOR là chỉ số chính",
  shop_tab: "Nhóm khách tự tìm đến · không có số liệu thêm vào giỏ",
  seller_video: "Nhóm nội dung · CTOR chỉ để tham khảo",
  seller_live: "Nhóm nội dung · CTOR chỉ để tham khảo",
  affiliate: "Nhóm nội dung · chỉ để hiểu toàn shop",
  affiliate_video: "Nhóm nội dung",
  affiliate_live: "Nhóm nội dung",
  total: "Toàn shop",
};

/** Backend `decomposition.FACTOR_LABELS`. */
export const FACTOR_LABELS: Record<FactorKey, string> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "CTR (Tỷ lệ nhấp)",
  ctor: "CTOR",
  aov: "AOV (SKU)",
};

/** Backend `heroes.RANKING_LABELS`. */
export const RANKING_LABELS: Record<string, string> = {
  "60d": "GMV 60 ngày gộp",
  "30d": "GMV 30 ngày gần nhất",
};

export const NOT_PROVIDED = "TikTok không cung cấp";
export const ESTIMATED = "ước tính";
export const BUY_NOW = "khách mua ngay";
export const CTOR_DIRECT = "gồm khách mua thẳng";
export const NO_DATA = "Chưa có dữ liệu";

/**
 * A channel the report carries no numbers for. Tab Cửa hàng is the known
 * case (its block can be absent from a shop's data — ADR-108 records the
 * shop-wide table that silently read it as zero); a channel row that is
 * missing, or whose two windows are both entirely zero, is shown as
 * "Chưa có dữ liệu" rather than as a channel that sold nothing.
 */
export function isChannelMissing(row: ChannelRow | undefined): boolean {
  if (!row) return true;
  const { prior, last } = row.comparison;
  const empty = (c: Counts) => !c.impressions && !c.clicks && !c.gmv;
  return empty(prior) && empty(last);
}

export function isSellerContent(channel: ChannelKey): boolean {
  return channel === "seller_video" || channel === "seller_live";
}
