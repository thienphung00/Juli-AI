// Per-product ads of the group campaigns (Connector 0.3.12, P97 T3): the manual-mpd page's table
// (Hiệu quả) → `ads_campaign_period`, one row per campaign x product over the window the page asked for.
//
// Source (recorded 2026-11-09, shape only): POST /api/pas/v1/product/mpd/list_item_product_performance/
// -- per product: views, clicks, CTR, ads cost, GMV (and selectable metrics). The request body was
// not captured, so the page's own request is the template (the window comes from its `start_time` /
// `end_time`) and the money scale is the ads service's (x100 000, like homepage/query).
//
// TODO(first capture, ORY): (1) the list's wrapper and the product id key (read: `item_id`,
// `itemid`, `product_id`, or the same inside `item` / `product`); (2) the per-product metric keys
// (read from `report` like the homepage entries: impression, click, ctr, cost, broad_gmv,
// direct_gmv, broad_order, direct_order, broad_roi, direct_roi); (3) the campaign title, which the
// scheduler passes from the ads list (the key the daily ads rows use). Policy as reader-map.ts:
// a missing product id, window or campaign title is drift (nothing posted, never guessed).

import { MAX_PLAUSIBLE_AD_VND, MONEY_DIVISOR, SHOPEE_NO_VALUE } from "../config";
import type { Drift, Mapped, Row } from "./map";
import { classify, findList, payloadOf, type ReaderResponse } from "./reader";

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

function put(row: Row, key: string, value: unknown): void {
  if (value !== undefined) row[key] = value;
}

/** The product id of one list entry: a top-level key, or inside a nested `item` / `product`. */
function productIdOf(entry: Record<string, unknown>): string | undefined {
  for (const key of ["item_id", "itemid", "product_id"]) {
    const id = digits(entry[key]);
    if (id !== undefined) return id;
  }
  for (const nested of [entry.item, entry.product]) {
    if (isRecord(nested)) {
      for (const key of ["item_id", "itemid", "product_id", "id"]) {
        const id = digits(nested[key]);
        if (id !== undefined) return id;
      }
    }
  }
  return undefined;
}

const hasReport = (o: Record<string, unknown>) => isRecord(o.report) && productIdOf(o) !== undefined;

function money(value: unknown): number | undefined {
  const n = nonNeg(value);
  if (n === undefined) return undefined;
  const vnd = Math.round((n / MONEY_DIVISOR.ads) * 100) / 100;
  return vnd <= MAX_PLAUSIBLE_AD_VND ? vnd : undefined;
}

export function mapAdsProducts(responses: ReaderResponse[], _capturedAt: number): Mapped[] {
  const answers = responses.filter((r) => r.endpoint === "ads_mpd_products" && classify(r.status, r.body) === "ok");
  const posts: Mapped[] = [];
  // One post per window (campaigns read together share the page's window).
  const windows = new Map<string, { period: { start: string; end: string }; rows: Row[] }>();
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  for (const answer of answers) {
    const name = answer.campaignName;
    if (!answer.period) {
      if (!issues.missing.includes("request.window")) issues.missing.push("request.window");
      continue;
    }
    if (!name) {
      if (!issues.missing.includes("campaign_name")) issues.missing.push("campaign_name");
      continue;
    }
    const found = findList(payloadOf(answer.body), hasReport);
    if (!found) {
      if (!issues.missing.includes("list[].item_id+report")) issues.missing.push("list[].item_id+report");
      continue;
    }
    const key = `${answer.period.start}|${answer.period.end}`;
    const slot = windows.get(key) ?? { period: answer.period, rows: [] };
    windows.set(key, slot);
    let ordinal = 0;
    for (const entry of found.list) {
      const id = productIdOf(entry);
      const report = isRecord(entry.report) ? entry.report : {};
      if (id === undefined) continue;
      const row: Row = { campaign_name: name.slice(0, 255), item_id: id, ordinal: ordinal++ };
      put(row, "ads_impressions", nonNeg(report.impression));
      put(row, "ad_clicks", nonNeg(report.click));
      put(row, "ctr", ctr(report.ctr));
      put(row, "ads_expense", money(report.cost));
      put(row, "sales", money(report.broad_gmv));
      put(row, "direct_sales", money(report.direct_gmv));
      put(row, "conversions", nonNeg(report.broad_order));
      put(row, "direct_conversions", nonNeg(report.direct_order));
      put(row, "product_views", nonNeg(report.product_impression ?? report.page_views));
      put(row, "product_clicks", nonNeg(report.product_click));
      slot.rows.push(row);
    }
  }
  const drift = driftOf(issues.unexpected, issues.missing);
  if (drift && windows.size === 0) {
    const today = new Date().toISOString().slice(0, 10);
    return [{ dataset: "ads_campaign_period", endpoint: "product/mpd/list_item_product_performance", date: today, orderType: "placed", granularity: "period", rows: [], drift }];
  }
  for (const { period, rows } of windows.values()) {
    posts.push({
      dataset: "ads_campaign_period",
      endpoint: "product/mpd/list_item_product_performance",
      date: period.end,
      periodStart: period.start,
      // The ads section counts placed orders (D85.3).
      orderType: "placed",
      granularity: "period",
      rows: drift ? [] : rows,
      drift,
    });
  }
  return posts;
}

function driftOf(unexpected: string[], missing: string[]): Drift | null {
  return unexpected.length || missing.length ? { unexpected, missing } : null;
}

/** A ratio the ads service sends as a fraction (0..1) or a percent (up to 100) -> a fraction. */
function ctr(value: unknown): number | undefined {
  const n = nonNeg(value);
  if (n === undefined) return undefined;
  return n <= 1 ? n : n <= 100 ? Math.round((n / 100) * 1e6) / 1e6 : undefined;
}
