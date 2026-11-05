import { ShopeeApiError } from "./client";
import type { ShopeeAds, ShopeeFlows, ShopeeKeywordBoard, ShopeeProducts, ShopeePromotions, ShopeeQuery } from "../ops/types";

/**
 * The Ops shop pages as the seller's read-only Demo pages (P92 B-8, `fasttrack/contracts/p92-api.md` §7):
 * Từ khóa, Quảng cáo + khuyến mãi, Đơn hàng, Sản phẩm + luồng. The SAME components run for the seller
 * (`/v1/demo/shopee/dashboard/*`, bearer + `X-Shop-Id`) and for Juli Ops (`/v1/ops/shops/{id}/shopee/*`,
 * bearer only): only the base, the dashboard prefix and the header differ, so a page takes a
 * {@link DashboardsApi} and never knows which one it holds. Every call is a GET; the shop id the Ops
 * components pass is ignored by the seller's client (the shop is in the header).
 */

export const DEMO_DASHBOARDS_BASE = "/v1/demo/shopee" as const;

export function opsDashboardsBase(shopId: string): string {
  return `/v1/ops/shops/${encodeURIComponent(shopId)}/shopee`;
}

export type OrderStatusKey = "delivered" | "refunded_accepted" | "in_transit" | "cancelled" | "refunded_not_received";
export type OrderLeverKey = "promotion" | "flash_sale" | "voucher" | "combo" | "affiliate";
export type OrdersPeriod = "7d" | "30d" | "90d" | "month" | "custom";

export interface OrdersQuery {
  readonly period?: OrdersPeriod;
  readonly month?: string;
  readonly from?: string;
  readonly to?: string;
  readonly status?: OrderStatusKey | null;
  readonly lever?: OrderLeverKey | null;
  readonly sort?: "date" | "gmv" | "contribution";
  readonly limit?: number;
  readonly offset?: number;
}

type N = number | null;

export interface OrderRow {
  /** The first 12 characters of the keyed hash; never a platform order id. */
  readonly order_key: string;
  readonly ordered_on: string;
  readonly status: OrderStatusKey | string;
  readonly lines: number;
  readonly units: number;
  readonly items: readonly string[];
  readonly levers: readonly string[];
  readonly gmv: N;
  readonly voucher: N;
  readonly promo_discount: N;
  readonly combo_discount: N;
  readonly buyer_paid: N;
  readonly fees: N;
  readonly fee_source?: string | null;
  readonly cogs: N;
  readonly contribution: N;
  readonly income: {
    readonly payout: N;
    readonly fees_total: N;
    readonly refund: N;
    readonly net_shipping_cost: N;
  } | null;
}

export interface ShopeeOrders {
  readonly platform?: string;
  readonly order_basis?: { readonly key: string; readonly label: string };
  readonly window?: { readonly from?: string; readonly to?: string; readonly days?: number };
  readonly sort?: string;
  readonly count: number;
  readonly offset: number;
  readonly limit: number;
  readonly by_status: Readonly<Record<string, number>>;
  readonly privacy?: string;
  readonly orders: readonly OrderRow[];
}

export interface DashboardsApi {
  shopeeProducts(shopId: string, q?: ShopeeQuery): Promise<ShopeeProducts>;
  shopeeFlows(shopId: string, q?: ShopeeQuery): Promise<ShopeeFlows>;
  shopeeAds(shopId: string, q?: ShopeeQuery): Promise<ShopeeAds>;
  shopeePromotions(shopId: string, q?: ShopeeQuery): Promise<ShopeePromotions>;
  shopeeKeywords(shopId: string, minVolume?: number): Promise<ShopeeKeywordBoard>;
  shopeeOrders(shopId: string, q?: OrdersQuery): Promise<ShopeeOrders>;
}

export interface DashboardsClientOptions {
  /** `DEMO_DASHBOARDS_BASE` or `opsDashboardsBase(shopId)`. */
  readonly base: string;
  /** `/dashboard` on the seller's routes, empty on Ops'. */
  readonly dashboardPrefix: "" | "/dashboard";
  readonly token: string;
  /** Seller scope only: the acting shop (`X-Shop-Id`). */
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

function dayQuery(q: ShopeeQuery, period: boolean): URLSearchParams {
  const p = new URLSearchParams();
  if (q.orderType) p.set("order_type", q.orderType);
  if (period) {
    if (q.periodFrom && q.periodTo) {
      p.set("period_from", q.periodFrom);
      p.set("period_to", q.periodTo);
    }
  } else {
    if (q.from) p.set("from", q.from);
    if (q.to) p.set("to", q.to);
  }
  return p;
}

function ordersQuery(q: OrdersQuery): URLSearchParams {
  const p = new URLSearchParams();
  if (q.period) p.set("period", q.period);
  if (q.period === "month" && q.month) p.set("month", q.month);
  if (q.period === "custom") {
    if (q.from) p.set("from", q.from);
    if (q.to) p.set("to", q.to);
  }
  if (q.status) p.set("status", q.status);
  if (q.lever) p.set("lever", q.lever);
  if (q.sort) p.set("sort", q.sort);
  if (q.limit) p.set("limit", String(q.limit));
  if (q.offset) p.set("offset", String(q.offset));
  return p;
}

function errorOf(status: number, payload: unknown): ShopeeApiError {
  let code = "";
  let message = `HTTP ${status}`;
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (typeof detail === "object" && detail !== null) {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string") message = d.message;
    }
  }
  return new ShopeeApiError(status, code, message);
}

export function createDashboardsApi(options: DashboardsClientOptions): DashboardsApi {
  const { base, dashboardPrefix, token, shopId, fetchImpl } = options;
  async function get<T>(path: string, params: URLSearchParams): Promise<T> {
    const qs = params.toString();
    const response = await (fetchImpl ?? fetch)(`${base}${path}${qs ? `?${qs}` : ""}`, {
      method: "GET",
      headers: { Accept: "application/json", Authorization: `Bearer ${token}`, ...(shopId ? { "X-Shop-Id": shopId } : {}) },
      cache: "no-store",
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) throw errorOf(response.status, payload);
    return payload as T;
  }
  const d = (name: string) => `${dashboardPrefix}/${name}`;
  return {
    shopeeProducts: (_shop, q = {}) => get<ShopeeProducts>(d("products"), dayQuery(q, true)),
    shopeeFlows: (_shop, q = {}) => get<ShopeeFlows>(d("flows"), dayQuery(q, false)),
    shopeeAds: (_shop, q = {}) => get<ShopeeAds>(d("ads"), dayQuery(q, false)),
    shopeePromotions: (_shop, q = {}) => get<ShopeePromotions>(d("promotions"), dayQuery(q, false)),
    shopeeKeywords: (_shop, minVolume) => get<ShopeeKeywordBoard>("/keywords", minVolume !== undefined ? new URLSearchParams({ min_volume: String(minVolume) }) : new URLSearchParams()),
    shopeeOrders: (_shop, q = {}) => get<ShopeeOrders>("/orders", ordersQuery(q)),
  };
}
