// Pure mapping: one Seller Centre /api/mydata JSON response → one ingest post.
//
// Field names come from the 2026-10-12 recon (~/shopee-corpus/seller-centre-internal,
// notes 01–02). A response that is not exactly one finished GMT+7 day maps to
// nothing. Unexpected or missing fields are DRIFT: the dataset is reported and
// stopped instead of guessing (D31.4). Item-level schemas were not observed (empty
// lists); those mappers are provisional until the second recon (D31.6) and check
// only that each item has an id.

import type { Dataset } from "../config";
import { ENDPOINTS } from "./endpoints";
import { singleDay } from "./time";

export { ENDPOINTS };

export type OrderType = "placed" | "paid" | "confirmed";
export type Row = Record<string, unknown>;

export interface Drift {
  unexpected: string[];
  missing: string[];
}

export interface Captured {
  url: string;
  body: unknown;
  capturedAt: number;
}

export interface Mapped {
  dataset: Dataset;
  endpoint: string;
  date: string;
  orderType: OrderType | null;
  rows: Row[];
  drift: Drift | null;
}

export const L1_SOURCES = [
  "psd_label_product_card",
  "psd_label_seller_live",
  "psd_label_seller_video",
  "psd_label_affiliate",
  "psd_label_shopee_ads",
] as const;

/** `result.<key>.total.source` must be the enum the key stands for. */
const SOURCE_KEYS: Record<string, (typeof L1_SOURCES)[number]> = {
  product_card: "psd_label_product_card",
  live: "psd_label_seller_live",
  video: "psd_label_seller_video",
  affiliate: "psd_label_affiliate",
  paid_ads: "psd_label_shopee_ads",
};

const RATIO_FIELDS = [
  "sales_ratio",
  "orders_ratio",
  "product_clicks_ratio",
  "content_views_ratio",
  "video_views_ratio",
  "live_views_ratio",
  "product_impressions_ratio",
];
const COMMON_METRICS = [
  "sales",
  "orders",
  "units",
  "buyers",
  "product_clicks",
  "unique_product_clicks",
  "sales_per_order",
  "ctr",
  "product_clicks_to_orders_rate",
];
const SOURCE_METRICS: Record<string, string[]> = {
  product_card: [...COMMON_METRICS, "product_impressions", "unique_product_impressions"],
  live: [...COMMON_METRICS, "live_views", "live_viewers"],
  video: [...COMMON_METRICS, "video_views", "video_viewers"],
  affiliate: [...COMMON_METRICS, "content_views", "content_viewers"],
  paid_ads: [
    "sales",
    "orders",
    "units",
    "product_impressions",
    "product_clicks",
    "ads_expense",
    "ads_roas",
    "live_views",
    "video_views",
    "ctr",
    "conversion",
  ],
};
const SOURCE_REQUIRED: Record<string, string[]> = {
  product_card: ["sales", "orders", "product_impressions", "product_clicks"],
  live: ["sales", "orders"],
  video: ["sales", "orders"],
  affiliate: ["sales", "orders"],
  paid_ads: ["sales", "orders", "ads_expense"],
};
/** Every metric name the gateway's source-row model accepts. */
const SOURCE_ROW_FIELDS = new Set([
  ...COMMON_METRICS,
  "product_impressions",
  "unique_product_impressions",
  "live_views",
  "live_viewers",
  "video_views",
  "video_viewers",
  "content_views",
  "content_viewers",
  "ads_expense",
  "ads_roas",
  "conversion",
]);
const RATE_FIELDS = new Set([
  "ctr",
  "product_clicks_to_orders_rate",
  "conversion",
  "bounce_rate",
  "atc_rate",
  "conversion_rate",
]);
const SHOP_TRAFFIC_FIELDS = [
  "page_views",
  "avg_page_views",
  "avg_stay_time",
  "bounce_rate",
  "visitors",
  "new_visitors",
  "existing_visitors",
  "new_followers",
];
const ITEM_PERFORMANCE_FIELDS: Record<string, string> = {
  sales: "sales",
  gmv: "sales",
  orders: "orders",
  order: "orders",
  units: "units",
  unit_num: "units",
  buyers: "buyers",
  product_impressions: "product_impressions",
  impressions: "product_impressions",
  product_clicks: "product_clicks",
  clicks: "product_clicks",
  ctr: "ctr",
  uv: "uv",
  product_visitors: "uv",
  pv: "pv",
  atc_uv: "atc_uv",
  atc_unit_num: "atc_units",
  atc_rate: "atc_rate",
  conversion_rate: "conversion_rate",
  order_conversion_rate: "conversion_rate",
};
const ID_FIELDS = ["item_id", "itemid", "product_id", "id"];
const NAME_FIELDS = ["item_name", "name", "product_name"];
const EXTRA_KEY = /^[A-Za-z0-9_.-]{1,64}$/;
const MAX_EXTRA = 60;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A metric value as a number, or undefined for absent / "-" / non-numeric. */
export function toNumber(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string" && value.trim() !== "" && value.trim() !== "-") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

/** `hh:mm:ss` (as the UI shows it) or a number of seconds → seconds. */
export function toSeconds(value: unknown): number | undefined {
  if (typeof value === "string" && /^\d{1,3}:\d{2}:\d{2}$/.test(value)) {
    const [h, m, s] = value.split(":").map(Number);
    return (h ?? 0) * 3600 + (m ?? 0) * 60 + (s ?? 0);
  }
  return toNumber(value);
}

function extraValue(value: unknown): unknown {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "boolean" || value === null) return value;
  if (typeof value === "string") return value.slice(0, 200);
  return undefined;
}

function addExtra(extra: Row, key: string, value: unknown): void {
  const kept = extraValue(value);
  if (kept === undefined || !EXTRA_KEY.test(key) || Object.keys(extra).length >= MAX_EXTRA) return;
  extra[key] = kept;
}

function unwrap(body: unknown): { result: unknown; drift: Drift | null } | null {
  if (!isObject(body)) return null;
  if (!("code" in body) || !("result" in body)) {
    return { result: null, drift: { unexpected: [], missing: ["code", "result"] } };
  }
  if (body.code !== 0) return null; // an error answer is not data, and not drift
  return { result: body.result, drift: null };
}

function orderTypeOf(params: URLSearchParams): OrderType {
  const value = params.get("order_type");
  return value === "placed" || value === "paid" ? value : "confirmed";
}

function scaleDrift(prefix: string, row: Row, drift: Drift): void {
  for (const [key, value] of Object.entries(row)) {
    if (RATE_FIELDS.has(key) && typeof value === "number" && (value < 0 || value > 1)) {
      drift.unexpected.push(`${prefix}${key}:not_a_fraction`);
    }
  }
}

function finish(drift: Drift): Drift | null {
  return drift.unexpected.length || drift.missing.length ? drift : null;
}

// -- datasets --------------------------------------------------------------------------

export function mapTrafficOverview(result: unknown, date: string): { rows: Row[]; drift: Drift | null } {
  const drift: Drift = { unexpected: [], missing: [] };
  if (!isObject(result)) return { rows: [], drift: { unexpected: [], missing: ["result"] } };
  const rows: Row[] = [];
  for (const key of Object.keys(result)) {
    if (key !== "overview" && !(key in SOURCE_KEYS)) drift.unexpected.push(`result.${key}`);
  }
  for (const [key, enumValue] of Object.entries(SOURCE_KEYS)) {
    const block = result[key];
    if (!isObject(block) || !isObject(block.total)) {
      drift.missing.push(`result.${key}.total`);
      continue;
    }
    const total = block.total;
    const metrics = SOURCE_METRICS[key] ?? [];
    const known = new Set(["source", ...metrics, ...RATIO_FIELDS]);
    const row: Row = { date, source: enumValue };
    const extra: Row = {};
    if (total.source !== enumValue) drift.unexpected.push(`result.${key}.source=${String(total.source)}`);
    for (const [field, value] of Object.entries(total)) {
      if (field.endsWith("_pct_diff")) {
        if (!known.has(field.slice(0, -"_pct_diff".length))) drift.unexpected.push(`result.${key}.${field}`);
        continue; // comparison vs the previous period: derivable, not stored
      }
      if (!known.has(field)) {
        drift.unexpected.push(`result.${key}.${field}`);
        continue;
      }
      if (field === "source") continue;
      if (RATIO_FIELDS.includes(field)) {
        addExtra(extra, field, toNumber(value));
        continue;
      }
      const number = toNumber(value);
      if (number !== undefined) row[field] = number;
    }
    for (const field of SOURCE_REQUIRED[key] ?? []) {
      if (!(field in total)) drift.missing.push(`result.${key}.${field}`);
    }
    if (Array.isArray(block.breakdown) && block.breakdown.length > 0) {
      // Level-2 sub-sources: schema pending the second recon (D31.6).
      addExtra(extra, "l2_breakdown_count", block.breakdown.length);
    }
    if (Object.keys(extra).length) row.extra = extra;
    scaleDrift(`result.${key}.`, row, drift);
    rows.push(row);
  }
  return { rows, drift: finish(drift) };
}

function itemIdOf(item: Record<string, unknown>): string | undefined {
  for (const field of ID_FIELDS) {
    const value = item[field];
    if (typeof value === "number" && Number.isInteger(value) && value >= 0) return String(value);
    if (typeof value === "string" && /^\d{1,32}$/.test(value)) return value;
  }
  return undefined;
}

function itemNameOf(item: Record<string, unknown>): string | undefined {
  for (const field of NAME_FIELDS) {
    const value = item[field];
    if (typeof value === "string" && value.trim()) return value.trim().slice(0, 255);
  }
  return undefined;
}

function mapItems(
  items: unknown,
  path: string,
  toRow: (item: Record<string, unknown>, id: string, name: string | undefined) => Row,
): { rows: Row[]; drift: Drift | null } {
  const drift: Drift = { unexpected: [], missing: [] };
  if (items === null || items === undefined) return { rows: [], drift: null };
  if (!Array.isArray(items)) return { rows: [], drift: { unexpected: [`${path}:not_a_list`], missing: [] } };
  const rows: Row[] = [];
  items.forEach((item, index) => {
    if (!isObject(item)) return;
    const id = itemIdOf(item);
    if (id === undefined) {
      if (!drift.missing.includes(`${path}[].item_id`)) drift.missing.push(`${path}[].item_id`);
      return;
    }
    const row = toRow(item, id, itemNameOf(item));
    scaleDrift(`${path}[${index}].`, row, drift);
    rows.push(row);
  });
  return { rows, drift: finish(drift) };
}

export function mapItemBySource(
  result: unknown,
  date: string,
  l1Source: string | null,
): { rows: Row[]; drift: Drift | null } {
  if (!l1Source || !(L1_SOURCES as readonly string[]).includes(l1Source)) {
    return { rows: [], drift: l1Source ? { unexpected: [`l1_source=${l1Source}`], missing: [] } : null };
  }
  if (!isObject(result)) return { rows: [], drift: { unexpected: [], missing: ["result"] } };
  return mapItems(result.item, "result.item", (item, id, name) => {
    const row: Row = { date, item_id: id, source: l1Source };
    if (name) row.item_name = name;
    const extra: Row = {};
    for (const [field, value] of Object.entries(item)) {
      if (ID_FIELDS.includes(field) || NAME_FIELDS.includes(field) || field.endsWith("_pct_diff")) continue;
      const number = toNumber(value);
      if (SOURCE_ROW_FIELDS.has(field)) {
        if (number !== undefined) row[field] = number;
      } else {
        addExtra(extra, field, value);
      }
    }
    if (Object.keys(extra).length) row.extra = extra;
    return row;
  });
}

export function mapItemPerformance(
  result: unknown,
  date: string,
  orderType: OrderType,
): { rows: Row[]; drift: Drift | null } {
  if (!isObject(result)) return { rows: [], drift: { unexpected: [], missing: ["result"] } };
  const prefixes = [`${orderType}_`, "placed_", "paid_", "confirmed_"];
  return mapItems(result.items, "result.items", (item, id, name) => {
    const row: Row = { date, item_id: id };
    if (name) row.item_name = name;
    const extra: Row = {};
    for (const [field, value] of Object.entries(item)) {
      if (ID_FIELDS.includes(field) || NAME_FIELDS.includes(field) || field.endsWith("_pct_diff")) continue;
      // `confirmed_sales` (order_by=confirmed_sales.desc) → `sales` for the chosen order type.
      const own = field.startsWith(`${orderType}_`) ? field.slice(orderType.length + 1) : field;
      const otherOrderType = own === field && prefixes.some((p) => field.startsWith(p));
      const target = otherOrderType ? undefined : ITEM_PERFORMANCE_FIELDS[own];
      const number = toNumber(value);
      if (target !== undefined && number !== undefined) {
        row[target] = number;
      } else {
        addExtra(extra, field, value);
      }
    }
    if (Object.keys(extra).length) row.extra = extra;
    return row;
  });
}

export function mapShopTraffic(result: unknown, date: string): { rows: Row[]; drift: Drift | null } {
  const drift: Drift = { unexpected: [], missing: [] };
  if (!isObject(result) || !isObject(result.data)) {
    return { rows: [], drift: { unexpected: [], missing: ["result.data"] } };
  }
  if (result.data_ready === false) return { rows: [], drift: null };
  const known = new Set(SHOP_TRAFFIC_FIELDS);
  const rows: Row[] = [];
  for (const device of Object.keys(result.data)) {
    if (device !== "all" && device !== "pc" && device !== "app") drift.unexpected.push(`result.data.${device}`);
  }
  for (const device of ["all", "pc", "app"] as const) {
    const block = result.data[device];
    if (!isObject(block)) {
      drift.missing.push(`result.data.${device}`);
      continue;
    }
    const row: Row = { date, device };
    for (const [field, value] of Object.entries(block)) {
      if (field.endsWith("_pct_diff")) {
        if (!known.has(field.slice(0, -"_pct_diff".length))) drift.unexpected.push(`result.data.${device}.${field}`);
        continue;
      }
      if (!known.has(field)) {
        drift.unexpected.push(`result.data.${device}.${field}`);
        continue;
      }
      const number = field === "avg_stay_time" ? toSeconds(value) : toNumber(value);
      if (number !== undefined) row[field] = number;
    }
    for (const field of ["visitors", "page_views"]) {
      if (!(field in block)) drift.missing.push(`result.data.${device}.${field}`);
    }
    scaleDrift(`result.data.${device}.`, row, drift);
    rows.push(row);
  }
  return { rows, drift: finish(drift) };
}

/** The dataset a Seller Centre URL feeds, or null. */
export function datasetOf(url: URL): Dataset | null {
  for (const [dataset, path] of Object.entries(ENDPOINTS) as [Dataset, string][]) {
    if (url.pathname === path) return dataset;
  }
  return null;
}

/** One captured response → one ingest post (or null when it is not a finished day). */
export function mapCaptured(captured: Captured): Mapped | null {
  let url: URL;
  try {
    url = new URL(captured.url, "https://banhang.shopee.vn");
  } catch {
    return null;
  }
  if (url.origin !== "https://banhang.shopee.vn") return null;
  const dataset = datasetOf(url);
  if (dataset === null) return null;
  const date = singleDay(url.searchParams, captured.capturedAt);
  if (date === null) return null;
  const unwrapped = unwrap(captured.body);
  if (unwrapped === null) return null;
  const orderType = dataset === "shop_traffic" ? null : orderTypeOf(url.searchParams);
  const base = { dataset, endpoint: ENDPOINTS[dataset], date, orderType };
  if (unwrapped.drift) return { ...base, rows: [], drift: unwrapped.drift };
  const result = unwrapped.result;
  let mapped: { rows: Row[]; drift: Drift | null };
  switch (dataset) {
    case "traffic_overview":
      mapped = mapTrafficOverview(result, date);
      break;
    case "item_by_source":
      mapped = mapItemBySource(result, date, url.searchParams.get("l1_source"));
      break;
    case "item_performance":
      mapped = mapItemPerformance(result, date, orderType ?? "confirmed");
      break;
    case "shop_traffic":
      mapped = mapShopTraffic(result, date);
      break;
  }
  return { ...base, ...mapped };
}
