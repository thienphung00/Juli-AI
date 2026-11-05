"use client";

import { useEffect, useState } from "react";

import { ShopeeApiError } from "./client";

/**
 * P92 B-10 "Giá thị trường": the product's price per unit against the page-1 listings of its
 * main keyword (contract `fasttrack/contracts/p92-api.md`, B-10). Same body for the seller
 * (`/v1/demo/shopee/...`) and Juli Ops (`/v1/ops/shops/{id}/shopee/...`). Nothing is invented:
 * `available: false` carries a reason and no numbers. Owner decision 2026-11-05: the seller's body has
 * only aggregates (median, average, count, unit, keyword, date, stale); `closest`, `keywords`,
 * `p25`, `p75` and `position` exist only in the Ops body.
 */

type N = number | null;

export type MarketReason = "no_keyword" | "no_capture" | "no_similar" | "market_closed";
export type MarketPosition = "below_p25" | "within" | "above_p75";

export interface MarketKeywordRow {
  readonly keyword: string;
  readonly collected_on: string | null;
  readonly age_days: N;
  readonly stale: boolean;
  readonly n_cards: N;
  readonly n_similar: N;
}

export interface MarketListing {
  readonly item_id: string;
  readonly name: string;
  readonly shop_name: string | null;
  readonly price: N;
  readonly price_min: N;
  readonly price_max: N;
  readonly pack_count: N;
  readonly price_per_unit: N;
  readonly sold_monthly: N;
  readonly sold_lifetime: N;
  readonly position: N;
  readonly is_ad?: boolean;
}

export interface MarketMarker {
  readonly price: N;
  readonly pack_count: N;
  readonly price_per_unit: N;
  /** Ops only (the P25-P75 range is not sent to the seller). */
  readonly position?: MarketPosition | null;
  readonly vs_median_pct: N;
  readonly vs_average_pct?: N;
}

export interface MarketPrice {
  readonly item_id: string;
  readonly name?: string | null;
  readonly available: boolean;
  readonly reason: MarketReason | null;
  readonly keyword?: string | null;
  readonly collected_on?: string | null;
  readonly age_days?: N;
  readonly stale?: boolean;
  readonly stale_after_days?: number;
  readonly keywords?: readonly MarketKeywordRow[];
  readonly unit?: { readonly key: string; readonly label: string; readonly per_label: string } | null;
  readonly own?: {
    readonly variation_id: string;
    readonly selling_price: N;
    readonly price_min: N;
    readonly price_max: N;
    readonly pack_count: N;
    readonly price_per_unit: N;
  } | null;
  readonly market?: {
    readonly n_similar: N;
    readonly median: N;
    /** Mean price per unit of the same similar set as the median. */
    readonly average?: N;
    /** Ops only: the seller (Demo) gets the median and average, never the range or the listings. */
    readonly p25?: N;
    readonly p75?: N;
    readonly own_vs_median_pct: N;
    readonly own_vs_average_pct?: N;
    readonly position?: MarketPosition | null;
  } | null;
  readonly closest?: readonly MarketListing[] | null;
  readonly marker?: MarketMarker | null;
  readonly note?: string | null;
}

/** Where the call goes: `base` is `/v1/demo/shopee` or `/v1/ops/shops/{id}/shopee` (an Ops analytics base is accepted too). */
export interface MarketScope {
  readonly base: string;
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

export interface MarketQuery {
  readonly variationId?: string;
  /** Draft selling price of the variation (VND): adds `marker`. */
  readonly price?: number | null;
  /** The lightweight builder call (no `closest`). */
  readonly range?: boolean;
}

export const MARKET_REASON_COPY: Readonly<Record<MarketReason, string>> = {
  no_keyword: "Sản phẩm chưa có từ khoá chính để tra giá thị trường.",
  no_capture: "Chưa đọc được trang tìm kiếm Shopee cho từ khoá của sản phẩm.",
  no_similar: "Chưa có sản phẩm tương tự (cùng quy cách) trong kết quả tìm kiếm.",
  market_closed: "Không đọc được dữ liệu thị trường bằng quyền hiện tại.",
};

export function marketBase(base: string): string {
  return base.replace(/\/analytics\/?$/, "");
}

export function marketUrl(base: string, itemId: string, q: MarketQuery = {}): string {
  const id = encodeURIComponent(itemId);
  const path = q.range ? `/builder/products/${id}/market-range` : `/products/${id}/market-price`;
  const params = new URLSearchParams();
  if (q.variationId !== undefined && q.variationId !== "") params.set("variation_id", q.variationId);
  if (q.price !== undefined && q.price !== null && Number.isFinite(q.price) && q.price > 0) params.set("price", String(Math.round(q.price)));
  const qs = params.toString();
  return `${marketBase(base)}${path}${qs ? `?${qs}` : ""}`;
}

export async function fetchMarketPrice(scope: MarketScope, itemId: string, q: MarketQuery = {}): Promise<MarketPrice> {
  const response = await (scope.fetchImpl ?? fetch)(marketUrl(scope.base, itemId, q), {
    method: "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${scope.token}`,
      ...(scope.shopId ? { "X-Shop-Id": scope.shopId } : {}),
    },
    cache: "no-store",
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok) {
    const detail = (payload as { detail?: { code?: unknown; message?: unknown } | string } | null)?.detail;
    if (detail && typeof detail === "object") {
      throw new ShopeeApiError(response.status, typeof detail.code === "string" ? detail.code : "", typeof detail.message === "string" ? detail.message : `HTTP ${response.status}`);
    }
    throw new ShopeeApiError(response.status, "", typeof detail === "string" ? detail : `HTTP ${response.status}`);
  }
  return payload as MarketPrice;
}

/** Pure: where a per-unit price sits against the market's P25 / median / P75. `null` when any bound or the price is unknown. */
export function markerPosition(
  perUnitPrice: N | undefined,
  range: { readonly p25: N | undefined; readonly p75: N | undefined; readonly median?: N | undefined },
): MarketPosition | null {
  const { p25, p75 } = range;
  if (perUnitPrice === null || perUnitPrice === undefined || p25 === null || p25 === undefined || p75 === null || p75 === undefined) return null;
  if (!(perUnitPrice > 0)) return null;
  if (perUnitPrice < p25) return "below_p25";
  if (perUnitPrice > p75) return "above_p75";
  return "within";
}

/** 0..100 position of `value` on a bar that spans `lo`..`hi`, clamped; `null` when it cannot be drawn. */
export function barPercent(value: N | undefined, lo: N | undefined, hi: N | undefined): number | null {
  if (value === null || value === undefined || lo === null || lo === undefined || hi === null || hi === undefined || hi <= lo) return null;
  return Math.max(0, Math.min(100, ((value - lo) / (hi - lo)) * 100));
}

export type MarketState =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string }
  | { readonly status: "ready"; readonly data: MarketPrice };

/** Loads the market price of a product (re-loads when the item, variation or draft price changes). `scope` null = idle. */
export function useMarketPrice(scope: MarketScope | null, itemId: string | null, q: MarketQuery = {}): MarketState {
  const key = `${scope?.base ?? ""}|${itemId ?? ""}|${q.variationId ?? ""}|${q.price ?? ""}|${q.range ? 1 : 0}`;
  const [done, setDone] = useState<{ readonly key: string; readonly state: MarketState } | null>(null);
  const base = scope?.base;
  const token = scope?.token;
  const shopId = scope?.shopId;
  const fetchImpl = scope?.fetchImpl;
  const active = !!base && !!token && !!itemId;
  useEffect(() => {
    if (!base || !token || !itemId) return;
    let live = true;
    fetchMarketPrice({ base, token, shopId, fetchImpl }, itemId, q).then(
      (data) => live && setDone({ key, state: { status: "ready", data } }),
      (error: unknown) => live && setDone({ key, state: { status: "error", message: error instanceof Error ? error.message : "Không tải được giá thị trường." } }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, token, shopId, fetchImpl, itemId, key]);
  if (!active) return { status: "idle" };
  return done && done.key === key ? done.state : { status: "loading" };
}
