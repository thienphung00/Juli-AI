// Product table (Connector 0.3.12, P97 T3): Phân tích bán hàng › Hiệu quả của sản phẩm → `product_period`.
//
// Source (recorded 2026-11-09, field names only): GET /api/mydata/v4/product/performance/ with
// period=past30days, 10 a page, order_by=confirmed_sales.desc. `result.{total, items[], need_upload_item}`;
// 49 keys per item -- id, name, image, status, display_tag_label, product_card_impressions /
// unique_*, product_card_clicks / unique_*, ctr, pv, uv, likes, bounce_visitors, bounce_rate,
// search_clicks, add_to_cart_units / buyers, {placed,paid,confirmed}_{sales,units,buyers,orders,
// sales_per_order}, *_order_conversion_rate, uv_to_*_rate, placed_to_paid_buyers_rate,
// placed_buyers_to_confirmed_buyers_rate, repeat_*_order_rate, average_days_to_repeat_* -- and
// `models[]` per variation (id, name, status, add_to_cart_*, placed_* / paid_* ...).
//
// One answer holds the placed, paid and confirmed values of an item, so one read posts both order
// types (D85.3): `confirmed` for Tổng quan, cards and plans, `placed` for Quảng cáo.
//
// TODO(first capture, ORY): (1) rates arrive as fractions or percents -- decided per answer
// (any rate above 1 means percents); (2) the exact spelling of the `repeat_*` / `average_days_*`
// keys (read as repeat_<order>_order_rate and average_days_to_repeat_<order>); (3) money is VND.
// Policy as reader-map.ts: an unexpected field is ignored; a missing result / items list, an item
// without an id, or no item with a sales value for an order type is drift (nothing posted).
// Item images and tags are never kept; item names are the seller's own listing text.

import { MAX_PLAUSIBLE_PRICE_VND, SHOPEE_NO_VALUE } from "../config";
import type { Drift, Mapped, OrderType, Row } from "./map";
import { classify, payloadOf, type ReaderResponse } from "./reader";
import { gmt7Date } from "./time";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNeg(value: unknown): number | undefined {
  if (value === SHOPEE_NO_VALUE) return undefined;
  const n = typeof value === "string" && value.trim() !== "" ? Number(value) : value;
  return typeof n === "number" && Number.isFinite(n) && n >= 0 ? n : undefined;
}

function digits(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) return String(value);
  if (typeof value === "string" && /^\d{1,32}$/.test(value)) return value;
  return undefined;
}

function text(value: unknown, max: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, max) : undefined;
}

/** A status that is a short word or a small number, as text. */
function status(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  const t = text(value, 64);
  return t !== undefined && /^[A-Za-z0-9_ .-]{1,64}$/.test(t) ? t : undefined;
}

const ORDER_PREFIX: Record<"confirmed" | "placed", string> = { confirmed: "confirmed", placed: "placed" };
export const PRODUCT_PERIOD_ORDER_TYPES = ["confirmed", "placed"] as const;
type PeriodOrderType = (typeof PRODUCT_PERIOD_ORDER_TYPES)[number];

/** Every rate-valued key of an item or variation (the ones the row model holds as fractions 0..1). */
function rateKeys(order: PeriodOrderType): string[] {
  const o = ORDER_PREFIX[order];
  return ["ctr", "bounce_rate", `${o}_order_conversion_rate`, `repeat_${o}_order_rate`];
}

/** True when the answer sends rates as percents (any rate above 1): then all are divided by 100. */
function percentScale(nodes: Record<string, unknown>[]): boolean {
  for (const node of nodes) {
    for (const order of PRODUCT_PERIOD_ORDER_TYPES) {
      for (const key of rateKeys(order)) {
        const n = nonNeg(node[key]);
        if (n !== undefined && n > 1) return true;
      }
    }
  }
  return false;
}

function put(row: Row, key: string, value: number | string | undefined): void {
  if (value !== undefined) row[key] = value;
}

function rowOf(node: Record<string, unknown>, order: PeriodOrderType, percent: boolean): Row {
  const o = ORDER_PREFIX[order];
  const rate = (key: string): number | undefined => {
    const n = nonNeg(node[key]);
    if (n === undefined) return undefined;
    return Math.round((percent ? n / 100 : n) * 1e6) / 1e6;
  };
  const row: Row = {};
  put(row, "sales", nonNeg(node[`${o}_sales`]));
  put(row, "orders", nonNeg(node[`${o}_orders`]));
  put(row, "units", nonNeg(node[`${o}_units`]));
  put(row, "buyers", nonNeg(node[`${o}_buyers`]));
  put(row, "sales_per_order", nonNeg(node[`${o}_sales_per_order`]));
  put(row, "conversion_rate", rate(`${o}_order_conversion_rate`));
  put(row, "repeat_purchase_rate", rate(`repeat_${o}_order_rate`));
  put(row, "repeat_purchase_days", nonNeg(node[`average_days_to_repeat_${o}`]));
  put(row, "product_impressions", nonNeg(node.product_card_impressions));
  put(row, "unique_product_impressions", nonNeg(node.unique_product_card_impressions));
  put(row, "product_clicks", nonNeg(node.product_card_clicks));
  put(row, "unique_product_clicks", nonNeg(node.unique_product_card_clicks));
  put(row, "ctr", rate("ctr"));
  put(row, "product_visitors", nonNeg(node.uv));
  put(row, "product_page_views", nonNeg(node.pv));
  put(row, "bounced_visitors", nonNeg(node.bounce_visitors));
  put(row, "bounce_rate", rate("bounce_rate"));
  put(row, "search_clicks", nonNeg(node.search_clicks));
  put(row, "likes", nonNeg(node.likes));
  put(row, "atc_visitors", nonNeg(node.add_to_cart_buyers));
  put(row, "atc_units", nonNeg(node.add_to_cart_units));
  return row;
}

function driftOf(unexpected: string[], missing: string[]): Drift | null {
  return unexpected.length || missing.length ? { unexpected, missing } : null;
}

/** The posts of one product-table read: one `product_period` post per order type. */
export function mapProductPeriod(responses: ReaderResponse[], capturedAt: number): Mapped[] {
  const answers = responses.filter((r) => r.endpoint === "product_performance" && classify(r.status, r.body) === "ok");
  if (answers.length === 0) return [];
  const today = gmt7Date(Math.floor(capturedAt / 1000));
  const range = answers.find((a) => a.period)?.period ?? { start: today, end: today };
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const items: Record<string, unknown>[] = [];
  for (const answer of answers) {
    const result = payloadOf(answer.body);
    if (!isRecord(result)) {
      if (!issues.missing.includes("result")) issues.missing.push("result");
      continue;
    }
    if (!("items" in result)) {
      if (!issues.missing.includes("result.items")) issues.missing.push("result.items");
      continue;
    }
    if (!Array.isArray(result.items)) {
      // `items: null` on a shop without sales is an empty page, not drift.
      if (result.items !== null && result.items !== undefined && !issues.unexpected.includes("result.items:not_a_list")) {
        issues.unexpected.push("result.items:not_a_list");
      }
      continue;
    }
    for (const item of result.items) if (isRecord(item)) items.push(item);
  }
  const seen = new Set<string>();
  const unique = items.filter((item) => {
    const id = digits(item.id ?? item.item_id);
    if (id === undefined) {
      if (!issues.missing.includes("items[].id")) issues.missing.push("items[].id");
      return false;
    }
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  const nodes = unique.flatMap((item) => [item, ...(Array.isArray(item.models) ? item.models.filter(isRecord) : [])]);
  const percent = percentScale(nodes);
  const posts: Mapped[] = [];
  for (const order of PRODUCT_PERIOD_ORDER_TYPES) {
    const rows: Row[] = [];
    const own = { unexpected: [...issues.unexpected], missing: [...issues.missing] };
    for (const item of unique) {
      const id = digits(item.id ?? item.item_id) as string;
      const row: Row = { item_id: id, ...rowOf(item, order, percent) };
      put(row, "item_name", text(item.name ?? item.item_name, 500));
      put(row, "item_status", status(item.status));
      rows.push(row);
      for (const model of Array.isArray(item.models) ? item.models.filter(isRecord) : []) {
        const modelId = digits(model.id ?? model.model_id);
        if (modelId === undefined) continue;
        const variation: Row = { item_id: id, variation_id: modelId, ...rowOf(model, order, percent) };
        put(variation, "variation_name", text(model.name, 255));
        put(variation, "variation_status", status(model.status));
        rows.push(variation);
      }
    }
    if (rows.length > 0 && !rows.some((r) => typeof r.sales === "number")) own.missing.push(`items[].${ORDER_PREFIX[order]}_sales`);
    if (rows.some((r) => typeof r.sales === "number" && r.sales > MAX_PLAUSIBLE_PRICE_VND * 1000)) own.unexpected.push("product_period:money_scale");
    const drift = driftOf(own.unexpected, own.missing);
    posts.push({
      dataset: "product_period",
      endpoint: "product/performance",
      date: range.end,
      periodStart: range.start,
      orderType: order as OrderType,
      granularity: "period",
      rows: drift ? [] : rows,
      drift,
    });
  }
  return posts;
}
