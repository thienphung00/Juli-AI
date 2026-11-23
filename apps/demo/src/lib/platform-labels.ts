/**
 * One label table per platform for traffic sources and stream terms (W3 U-1).
 *
 * Every screen that names a source (Thẻ sản phẩm, Trang shop / Tab cửa hàng, Video, Live, Tiếp thị liên kết,
 * Dịch vụ hiển thị / Quảng cáo) reads it here, so a term is spelled once per marketplace. Shopee strings are
 * unchanged from the maps this table replaced; TikTok follows decision #7:
 * Organic = Thẻ sản phẩm + Video + LIVE, TTLK = Tiếp thị liên kết, these four sum to the shop total, Tab cửa hàng
 * is shown outside the total (`inTotal: false`), Quảng cáo is "—" until the Business API scope exists.
 */

import type { NavPlatform } from "./app-navigation";

/** The source keys in the URL / layer 4 (`source_metrics_daily.source`). */
export type SourceKey = "all" | "the_san_pham" | "trang_shop" | "live" | "video" | "lien_ket" | "ads";

export interface SourceLabel {
  /** The name on chips, headings and breadcrumbs. */
  readonly name: string;
  /** The name in a funnel row (Quyết định "Chi tiết" by source). */
  readonly funnel: string;
  /** Counted in the shop total? Tab cửa hàng overlaps the other sources on TikTok, so it is not. */
  readonly inTotal: boolean;
  /** The platform gives no numbers for this source: every metric shows "—". */
  readonly unavailable: boolean;
}

const src = (name: string, funnel = name, inTotal = true, unavailable = false): SourceLabel => ({ name, funnel, inTotal, unavailable });

export const SOURCE_LABEL_TABLE: Readonly<Record<NavPlatform, Readonly<Record<SourceKey, SourceLabel>>>> = {
  shopee: {
    all: src("Tất cả"),
    the_san_pham: src("Thẻ sản phẩm", "Thẻ sản phẩm (ngoài Trang shop)"),
    trang_shop: src("Trang shop"),
    live: src("Live"),
    video: src("Video"),
    lien_ket: src("Tiếp thị liên kết", "Liên kết"),
    ads: src("Dịch vụ hiển thị"),
  },
  tiktok: {
    all: src("Tất cả"),
    the_san_pham: src("Thẻ sản phẩm"),
    trang_shop: src("Tab cửa hàng", "Tab cửa hàng", false),
    live: src("LIVE"),
    video: src("Video"),
    lien_ket: src("Tiếp thị liên kết"),
    ads: src("Quảng cáo", "Quảng cáo", true, true),
  },
};

/** Source key for a funnel / flow key from the API (`the_san_pham_khac` is Thẻ sản phẩm). */
export function sourceKeyOfFlow(apiKey: string): string {
  return apiKey === "the_san_pham_khac" ? "the_san_pham" : apiKey;
}

export function isSourceKey(key: string): key is SourceKey {
  return key in SOURCE_LABEL_TABLE.shopee;
}

/** The offer-type filters of the source chips (`src=`), the same on both platforms. */
export const OFFER_NAME_TABLE: Readonly<Record<string, string>> = { none: "Không ưu đãi", voucher: "Voucher", promo: "Khuyến mãi", combo: "Combo" };

/** The name of a source on a platform; an unknown key is returned as is. */
export function sourceName(platform: NavPlatform, key: string): string {
  if (key in OFFER_NAME_TABLE) return OFFER_NAME_TABLE[key]!;
  const k = sourceKeyOfFlow(key);
  return isSourceKey(k) ? SOURCE_LABEL_TABLE[platform][k].name : key;
}

/** The name of a source in a funnel row, or null when the key is not a source (the caller falls back). */
export function sourceFunnelName(platform: NavPlatform, apiKey: string): string | null {
  if (apiKey === "chenh_lech_nguon") return "Chênh lệch nguồn";
  const k = sourceKeyOfFlow(apiKey);
  return isSourceKey(k) ? SOURCE_LABEL_TABLE[platform][k].funnel : null;
}

/** Sources outside the shop total on a platform (TikTok: Tab cửa hàng). */
export function sourcesOutsideTotal(platform: NavPlatform): readonly SourceKey[] {
  return (Object.keys(SOURCE_LABEL_TABLE[platform]) as SourceKey[]).filter((k) => !SOURCE_LABEL_TABLE[platform][k].inTotal);
}

/** True when the platform gives no numbers for the source (render "—", never 0). */
export function sourceUnavailable(platform: NavPlatform, key: string): boolean {
  const k = sourceKeyOfFlow(key);
  return isSourceKey(k) && SOURCE_LABEL_TABLE[platform][k].unavailable;
}

/** Stream ids used by the Ops screens (`product_card`, `shop_tab`, `seller_video`, `seller_live`, `affiliate`). */
export type StreamKey = "product_card" | "shop_tab" | "seller_video" | "seller_live" | "affiliate";

export const STREAM_LABEL_TABLE: Readonly<Record<NavPlatform, Readonly<Partial<Record<StreamKey, string>>>>> = {
  tiktok: { product_card: "Thẻ sản phẩm", shop_tab: "Tab cửa hàng", seller_video: "Video", seller_live: "LIVE" },
  shopee: { product_card: "Thẻ sản phẩm", seller_video: "Video", seller_live: "Live", affiliate: "Tiếp thị liên kết" },
};

/** Short stream names for a settings summary line. */
export const STREAM_SHORT_LABEL_TABLE: Readonly<Record<NavPlatform, Readonly<Partial<Record<StreamKey, string>>>>> = {
  tiktok: { product_card: "Thẻ SP", shop_tab: "Tab", seller_video: "Video", seller_live: "LIVE" },
  shopee: { product_card: "Thẻ SP", seller_video: "Video", seller_live: "Live", affiliate: "TTLK" },
};

export function streamName(platform: NavPlatform, id: string): string {
  return STREAM_LABEL_TABLE[platform][id as StreamKey] ?? id;
}

export function streamShortName(platform: NavPlatform, id: string): string {
  return STREAM_SHORT_LABEL_TABLE[platform][id as StreamKey] ?? id;
}

/** Other terms that were spelled in several places. */
export const TERM_LABEL_TABLE: Readonly<Record<NavPlatform, { readonly affiliate: string; readonly allChannels: string; readonly kol: string }>> = {
  tiktok: { affiliate: "Tiếp thị liên kết", allChannels: "Tất cả kênh", kol: "Tiếp thị liên kết theo KOL" },
  shopee: { affiliate: "Tiếp thị liên kết", allChannels: "Tất cả kênh", kol: "Tiếp thị liên kết theo KOL" },
};

/** Tổng quan channel-split row keys → the source they are. */
const CHANNEL_KEY_SOURCE: Readonly<Record<string, SourceKey>> = {
  organic_card: "the_san_pham",
  organic_shop: "trang_shop",
  organic_video: "video",
  organic_live: "live",
  affiliate: "lien_ket",
};

/** Names of the channel-split rows of Tổng quan (`ChannelKey`). TikTok has no DVHT: its ad rows read Quảng cáo. */
export function channelName(platform: NavPlatform, key: string): string {
  if (key === "organic") return "Organic";
  if (key === "ads") return "Quảng cáo";
  if (key === "ads_product") return platform === "shopee" ? "DVHT Sản phẩm" : "Quảng cáo";
  if (key === "ads_shop") return platform === "shopee" ? "DVHT Shop+" : "Quảng cáo";
  const source = CHANNEL_KEY_SOURCE[key];
  return source ? sourceName(platform, source) : key;
}

/** Names of the Phân tích `channel` values (the luồng a row opens); null when the key is not a channel. */
export function channelLabel(platform: NavPlatform, key: string): string | null {
  if (key === "ads_product" || key === "ads_shop") return channelName(platform, key);
  return isSourceKey(key) && key !== "all" && key !== "ads" ? sourceName(platform, key) : null;
}

/** The marketplace's name on the platform chip and in "no data yet" titles. */
export const PLATFORM_NAME_TABLE: Readonly<Record<NavPlatform, string>> = { shopee: "Shopee", tiktok: "TikTok Shop" };

const OUTSIDE_TOTAL_BLANK_CELLS: ReadonlySet<string> = new Set(["orders", "ctor", "aov"]);

/** The source a Tổng quan channel row is (`organic_shop` is Tab cửa hàng); null for the parents. */
export function sourceOfChannelKey(key: string): SourceKey | null {
  if (key === "ads" || key === "ads_product" || key === "ads_shop") return "ads";
  return CHANNEL_KEY_SOURCE[key] ?? null;
}

/** Is the channel row outside the shop total on this platform (TikTok: Tab cửa hàng)? */
export function channelOutsideTotal(platform: NavPlatform, key: string): boolean {
  const source = sourceOfChannelKey(key);
  return source !== null && !SOURCE_LABEL_TABLE[platform][source].inTotal;
}

/**
 * A cell the platform never gives, whatever the response carries: it shows "—", never 0 (R-2).
 * TikTok: every figure of Quảng cáo (no Business API scope yet); orders / CTOR / AOV of Tab cửa hàng.
 */
export function channelCellBlank(platform: NavPlatform, key: string, cell: string): boolean {
  const source = sourceOfChannelKey(key);
  if (source === null) return false;
  if (SOURCE_LABEL_TABLE[platform][source].unavailable) return true;
  return channelOutsideTotal(platform, key) && OUTSIDE_TOTAL_BLANK_CELLS.has(cell);
}

/** Rows in display order: rows outside the total go last, standing alone (not children of Organic). */
export function channelRowsForDisplay<R extends { readonly key: string; readonly parent: string | null }>(platform: NavPlatform, rows: readonly R[]): readonly R[] {
  const outside = rows.filter((r) => channelOutsideTotal(platform, r.key)).map((r) => ({ ...r, parent: null }) as R);
  return [...rows.filter((r) => !channelOutsideTotal(platform, r.key)), ...outside];
}
