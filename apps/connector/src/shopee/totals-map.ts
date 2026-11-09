// Shop totals (Connector 0.3.11, P97 T1): Phân tích bán hàng › Tổng quan → `shop_overview`.
//
// Source (recon 2026-11-09, field names only): GET /api/mydata/v3/dashboard/key-metrics/ holds
// `place_*`, `paid_*`, `confirmed_*` gmv / orders / sales_per_order and
// `*_gmv_without_shopee_rebate`, plus `shop_pv`, `shop_uv`, `product_clicks`, each
// `{value, chain_ratio, points[{timestamp, value}]}`. GET /api/mydata/dashboard/order-performance/
// holds `cancelled_*` / `return_refund_*` (confirmed basis). One answer covers placed + paid +
// confirmed (D85.3), so one request posts all three order types.
//
// TODO(first capture, ORY): (1) the `period` / `start_time` / `end_time` shape that makes `points`
// daily for a multi-day range (the reader sends period=past30days|past7days with the range's
// bounds); (2) whether `timestamp` is seconds or ms (both are read); (3) money unit (read as VND,
// like the other mydata answers). Until confirmed, an answer with no daily points maps to nothing
// (drift: missing `points`), never to a guessed number.
//
// Policy as reader-map.ts: an unexpected extra field is ignored (never drift); a missing GMV
// metric for every order type, or no daily points, is drift (dataset stopped, nothing posted).

import { SHOPEE_NO_VALUE } from "../config";
import type { Drift, Mapped, OrderType, Row } from "./map";
import { classify, payloadOf, type ReaderResponse } from "./reader";
import { gmt7Date } from "./time";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function num(value: unknown): number | undefined {
  if (value === SHOPEE_NO_VALUE) return undefined;
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : undefined;
}

/** `place` is what Seller Centre calls placed in field names; `placed` is accepted too. */
const PREFIXES: Record<OrderType, readonly string[]> = {
  placed: ["place", "placed"],
  paid: ["paid"],
  confirmed: ["confirmed"],
};
const ORDER_TYPES: readonly OrderType[] = ["confirmed", "placed", "paid"];

/** A metric's daily series: GMT+7 day → value. */
function series(metric: unknown, single?: string): Map<string, number> {
  const out = new Map<string, number>();
  if (!isRecord(metric)) return out;
  const points = Array.isArray(metric.points) ? metric.points : [];
  for (const point of points) {
    if (!isRecord(point)) continue;
    const t = num(point.timestamp);
    const v = num(point.value);
    if (t === undefined || v === undefined) continue;
    out.set(gmt7Date(Math.floor(t > 1e12 ? t / 1000 : t)), v);
  }
  // A one-day answer may carry only the headline value.
  if (out.size === 0 && single !== undefined) {
    const v = num(metric.value);
    if (v !== undefined) out.set(single, v);
  }
  return out;
}

function pick(payload: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) if (key in payload) return payload[key];
  return undefined;
}

export interface TotalsRange {
  start: string;
  end: string;
}

/** The posts of one shop-totals read: one `shop_overview` post per order type that has days. */
export function mapShopTotals(responses: ReaderResponse[], capturedAt: number): Mapped[] {
  const ok = (endpoint: ReaderResponse["endpoint"]) =>
    responses.filter((r) => r.endpoint === endpoint && classify(r.status, r.body) === "ok");
  const metrics = ok("shop_key_metrics")[0];
  if (!metrics) return [];
  const range = metrics.period ?? { start: gmt7Date(Math.floor(capturedAt / 1000)), end: gmt7Date(Math.floor(capturedAt / 1000)) };
  const single = range.start === range.end ? range.start : undefined;
  const payload = payloadOf(metrics.body);
  const drift: Drift = { unexpected: [], missing: [] };
  if (!isRecord(payload)) return [empty(range, { unexpected: [], missing: ["key_metrics"] })];

  const traffic = {
    product_clicks: series(pick(payload, ["product_clicks", "item_clicks"]), single),
    visitors: series(pick(payload, ["shop_uv", "uv"]), single),
    pv: series(pick(payload, ["shop_pv", "pv"]), single),
  };

  const performance = ok("shop_order_performance")[0];
  const perfPayload = performance ? payloadOf(performance.body) : null;
  const cancelled = {
    orders: series(isRecord(perfPayload) ? perfPayload.cancelled_orders : undefined, single),
    sales: series(isRecord(perfPayload) ? perfPayload.cancelled_sales : undefined, single),
    returnedOrders: series(isRecord(perfPayload) ? perfPayload.return_refund_orders : undefined, single),
    returnedSales: series(isRecord(perfPayload) ? perfPayload.return_refund_sales : undefined, single),
  };

  const posts: Mapped[] = [];
  let sawGmv = false;
  for (const orderType of ORDER_TYPES) {
    const keys = (suffix: string) => PREFIXES[orderType].map((p) => `${p}_${suffix}`);
    const gmv = series(pick(payload, keys("gmv")), single);
    const orders = series(pick(payload, keys("orders")), single);
    const perOrder = series(pick(payload, keys("sales_per_order")), single);
    const withoutRebate = series(pick(payload, keys("gmv_without_shopee_rebate")), single);
    if (pick(payload, keys("gmv")) !== undefined) sawGmv = true;
    // Only the days asked for (a finished-day range): a partial "today" point is never posted.
    const days = [...new Set([...gmv.keys(), ...orders.keys()])]
      .filter((d) => d >= range.start && d <= range.end)
      .sort();
    if (days.length === 0) continue;
    const rows: Row[] = [];
    for (const day of days) {
      const row: Row = { date: day };
      const sales = gmv.get(day);
      const count = orders.get(day);
      if (sales !== undefined) row.sales = sales;
      if (count !== undefined) row.orders = count;
      const aov = perOrder.get(day) ?? (sales !== undefined && count ? Math.round((sales / count) * 100) / 100 : undefined);
      if (aov !== undefined) row.sales_per_order = aov;
      const excl = withoutRebate.get(day);
      if (excl !== undefined) row.sales_excl_shopee_subsidy = excl;
      const clicks = traffic.product_clicks.get(day);
      const visitors = traffic.visitors.get(day);
      const pv = traffic.pv.get(day);
      if (clicks !== undefined) row.product_clicks = clicks;
      if (visitors !== undefined) row.visitors = visitors;
      if (pv !== undefined) row.extra = { shop_pv: pv };
      if (orderType === "confirmed") {
        const co = cancelled.orders.get(day);
        const cs = cancelled.sales.get(day);
        const ro = cancelled.returnedOrders.get(day);
        const rs = cancelled.returnedSales.get(day);
        if (co !== undefined) row.cancelled_orders = co;
        if (cs !== undefined) row.cancelled_sales = cs;
        if (ro !== undefined) row.returned_orders = ro;
        if (rs !== undefined) row.returned_sales = rs;
      }
      rows.push(row);
    }
    posts.push({
      dataset: "shop_overview",
      endpoint: "dashboard/key-metrics",
      date: days[days.length - 1] as string,
      periodStart: days[0] as string,
      orderType,
      granularity: "day",
      rows,
      drift: null,
    });
  }
  if (posts.length === 0) {
    drift.missing.push(sawGmv ? "key_metrics.points" : "key_metrics.confirmed_gmv");
    return [empty(range, drift)];
  }
  return posts;
}

function empty(range: TotalsRange, drift: Drift): Mapped {
  return {
    dataset: "shop_overview",
    endpoint: "dashboard/key-metrics",
    date: range.end,
    periodStart: range.start,
    orderType: "confirmed",
    granularity: "day",
    rows: [],
    drift,
  };
}
