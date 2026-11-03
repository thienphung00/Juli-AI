// Pure mapping: the responses of one reader job → ingest posts (ADR-120 d.14).
//
// Field names come from the 2026-11-03 recon of the ORY Seller Centre (response SHAPES only;
// docs/integrations/shopee/seller-centre-recon-2026-11-03.md). Where the recon did not pin a
// wrapper or a unit the mapper is tolerant (it finds the list by its element shape) and the
// open points are named in the reader report. Policy, unlike the `/api/mydata` mappers:
// an UNEXPECTED field is not drift (the recon list is partial); a MISSING identity field, a
// list that cannot be found, or an implausible money scale is drift (dataset stopped, nothing
// posted). Strings the contract does not name never leave the browser.

import { MAX_PLAUSIBLE_AD_VND, MAX_PLAUSIBLE_PRICE_VND, MONEY_DIVISOR } from "../config";
import type { Drift, Mapped, Row } from "./map";
import {
  classify,
  findList,
  isAdsEntry,
  isProduct,
  isVoucher,
  payloadOf,
  type ReaderJob,
  type ReaderResponse,
  totalOf,
} from "./reader";
import { gmt7Date } from "./time";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** A finite number from a number or numeric string; undefined otherwise. */
export function num(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value === "string" && value.trim() !== "" && value.trim() !== "-") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

/** A non-negative number (counts, money, ratios), else undefined. */
function nonNeg(value: unknown): number | undefined {
  const n = num(value);
  return n !== undefined && n >= 0 ? n : undefined;
}

function money(value: unknown, divisor: number): number | undefined {
  const n = nonNeg(value);
  return n === undefined ? undefined : Math.round((n / divisor) * 100) / 100;
}

function text(value: unknown, max: number): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed.slice(0, max) : undefined;
}

/** A platform enum sent as a number or a short label. */
function tag(value: unknown): number | string | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  return text(value, 64);
}

function flag(value: unknown): boolean | undefined {
  if (typeof value === "boolean") return value;
  if (value === 0 || value === 1) return value === 1;
  return undefined;
}

function digits(value: unknown): string | undefined {
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) return String(value);
  if (typeof value === "string" && /^\d{1,32}$/.test(value)) return value;
  return undefined;
}

/** Unix seconds (or ms) → an ISO UTC instant. */
function instant(value: unknown): string | undefined {
  const n = num(value);
  if (n === undefined || n <= 0) return undefined;
  return new Date((n > 1e12 ? n : n * 1000)).toISOString();
}

/** Unix seconds (or ms) → Seller Centre's wall clock (GMT+7), no zone suffix. */
function wallClock(value: unknown): string | undefined {
  const n = num(value);
  if (n === undefined || n <= 0) return undefined;
  const seconds = n > 1e12 ? Math.floor(n / 1000) : n;
  return new Date((seconds + 7 * 3600) * 1000).toISOString().slice(0, 19);
}

function put(row: Row, key: string, value: unknown): void {
  if (value !== undefined) row[key] = value;
}

function driftOf(unexpected: string[], missing: string[]): Drift | null {
  return unexpected.length || missing.length ? { unexpected, missing } : null;
}

/** The answers that carry data: the first non-data verdict (if any) means nothing to map. */
function dataResponses(responses: ReaderResponse[], endpoint: string): ReaderResponse[] {
  return responses.filter((r) => r.endpoint === endpoint && classify(r.status, r.body) === "ok");
}

const todayOf = (capturedAt: number) => gmt7Date(Math.floor(capturedAt / 1000));

// -- products ------------------------------------------------------------------------------

function stockFields(source: unknown): Row {
  const row: Row = {};
  if (!isRecord(source)) return row;
  put(row, "total_available_stock", nonNeg(source.total_available_stock));
  put(row, "total_seller_stock", nonNeg(source.total_seller_stock));
  put(row, "total_shopee_stock", nonNeg(source.total_shopee_stock));
  put(row, "low_stock_status", tag(source.low_stock_status));
  const advanced = source.advanced_stock;
  if (isRecord(advanced)) {
    put(row, "sellable_stock", nonNeg(advanced.sellable_stock));
    put(row, "in_transit_stock", nonNeg(advanced.in_transit_stock));
  }
  return row;
}

/** Items → active-campaign counts, from the page's own `get_campaign_info_by_item_list` answer. */
export function campaignCounts(body: unknown): Map<string, number> {
  const counts = new Map<string, number>();
  const found = findList(payloadOf(body), (o) => digits(o.item_id ?? o.id ?? o.itemid) !== undefined);
  for (const entry of found?.list ?? []) {
    const id = digits(entry.item_id ?? entry.id ?? entry.itemid);
    const nested = Object.values(entry).find((v) => Array.isArray(v));
    if (id !== undefined && Array.isArray(nested)) counts.set(id, nested.length);
  }
  return counts;
}

export interface ProductMapping {
  catalog: Mapped;
  snapshot: Mapped;
}

export function mapProductList(responses: ReaderResponse[], capturedAt: number): ProductMapping {
  const date = todayOf(capturedAt);
  const unexpected: string[] = [];
  const missing: string[] = [];
  const items = new Map<string, Record<string, unknown>>();
  for (const response of dataResponses(responses, "product_list")) {
    const found = findList(payloadOf(response.body), isProduct);
    if (!found) {
      // An empty first page is an empty shop; a first page with no list at all is drift.
      if (response.page === 1 && (totalOf(response.body) ?? 1) > 0 && !missing.includes("products")) {
        missing.push("products");
      }
      continue;
    }
    for (const item of found.list) {
      const id = digits(item.id ?? item.item_id);
      if (id === undefined) {
        if (!missing.includes("products[].id")) missing.push("products[].id");
        continue;
      }
      if (!items.has(id)) items.set(id, item);
    }
  }
  const campaigns = new Map<string, number>();
  for (const response of dataResponses(responses, "campaign_info")) {
    for (const [id, count] of campaignCounts(response.body)) campaigns.set(id, count);
  }

  const divisor = MONEY_DIVISOR.products;
  const catalogRows: Row[] = [];
  const snapshotRows: Row[] = [];
  for (const [id, item] of items) {
    const itemRow: Row = { item_id: id };
    put(itemRow, "item_name", text(item.name, 500));
    put(itemRow, "seller_sku", text(item.parent_sku, 100));
    put(itemRow, "status", tag(item.status) === undefined ? undefined : String(tag(item.status)));
    catalogRows.push(itemRow);

    const price = isRecord(item.price_detail) ? item.price_detail : {};
    const snap: Row = { item_id: id };
    put(snap, "image", text(item.cover_image, 300));
    put(snap, "create_time", instant(item.create_time));
    put(snap, "modify_time", instant(item.modify_time));
    put(snap, "price_min", money(price.price_min, divisor));
    put(snap, "price_max", money(price.price_max, divisor));
    put(snap, "selling_price_min", money(price.selling_price_min, divisor));
    put(snap, "selling_price_max", money(price.selling_price_max, divisor));
    put(snap, "has_discount", flag(price.has_discount));
    const percent = nonNeg(price.max_discount_percentage);
    put(snap, "discount_percent", percent !== undefined && percent <= 100 ? percent : undefined);
    put(snap, "max_discount", money(price.max_discount, divisor));
    Object.assign(snap, stockFields(item.stock_detail));
    const stats = isRecord(item.statistics) ? item.statistics : {};
    put(snap, "view_count", nonNeg(stats.view_count));
    put(snap, "liked_count", nonNeg(stats.liked_count));
    put(snap, "sold_count", nonNeg(stats.sold_count));
    const tags = isRecord(item.tag) ? item.tag : {};
    const promotion = isRecord(item.promotion) ? item.promotion : {};
    put(snap, "promo_has_discount", flag(tags.has_discount));
    put(snap, "promo_has_bundle_deal", flag(tags.has_bundle_deal) ?? flag(promotion.has_bundle_deal));
    put(snap, "promo_has_add_on_deal", flag(tags.has_add_on_deal));
    put(snap, "promo_has_ams_commission", flag(tags.has_ams_commission));
    put(snap, "promo_wholesale", flag(promotion.wholesale) ?? (Array.isArray(promotion.wholesale) ? promotion.wholesale.length > 0 : undefined));
    put(snap, "unlisted", flag(tags.unlist));
    put(snap, "campaign_count", campaigns.get(id));
    snapshotRows.push(snap);

    if (price.price_max !== undefined && (nonNeg(price.price_max) ?? 0) / divisor > MAX_PLAUSIBLE_PRICE_VND) {
      if (!unexpected.includes("price_detail.price_max:money_scale")) unexpected.push("price_detail.price_max:money_scale");
    }

    const models = Array.isArray(item.model_list) ? item.model_list.filter(isRecord) : [];
    for (const model of models) {
      const modelId = digits(model.id);
      if (modelId === undefined) {
        if (!missing.includes("model_list[].id")) missing.push("model_list[].id");
        continue;
      }
      const variation: Row = { item_id: id, variation_id: modelId };
      put(variation, "variation_name", text(model.name, 255));
      put(variation, "seller_sku", text(model.sku, 100));
      catalogRows.push(variation);

      const modelPrice = isRecord(model.price_detail) ? model.price_detail : {};
      const row: Row = { item_id: id, model_id: modelId };
      put(row, "image", text(model.image, 300));
      put(row, "origin_price", money(modelPrice.origin_price, divisor));
      put(row, "promotion_price", money(modelPrice.promotion_price, divisor));
      Object.assign(row, stockFields(model.stock_detail));
      const modelStats = isRecord(model.statistics) ? model.statistics : {};
      put(row, "sold_count", nonNeg(modelStats.sold_count));
      put(row, "is_default", flag(model.is_default));
      if (Array.isArray(model.tier_index) && model.tier_index.every((v) => typeof v === "number")) {
        row.tier_index = model.tier_index.join(",").slice(0, 32);
      }
      snapshotRows.push(row);
    }
  }
  const drift = driftOf(unexpected, missing);
  const base = { date, orderType: null, granularity: "period" as const, drift };
  return {
    catalog: { ...base, dataset: "item_catalog", endpoint: "get_product_list", rows: drift ? [] : catalogRows },
    snapshot: { ...base, dataset: "item_snapshot", endpoint: "get_product_list", rows: drift ? [] : snapshotRows },
  };
}

// -- per-product traffic sources -------------------------------------------------------------

const STATUS_NORMAL = new Set(["1", "normal", "active", "live"]);

/**
 * Item ids worth a traffic read: not unlisted, and a normal status (when none of the statuses
 * looks normal the unlisted filter alone applies, so an unknown status code reads more, not less).
 */
export function activeItemIds(responses: ReaderResponse[]): string[] {
  const unlistedOut: { id: string; normal: boolean }[] = [];
  const seen = new Set<string>();
  for (const response of dataResponses(responses, "product_list")) {
    const found = findList(payloadOf(response.body), isProduct);
    for (const item of found?.list ?? []) {
      const id = digits(item.id ?? item.item_id);
      if (id === undefined || seen.has(id)) continue;
      seen.add(id);
      const tags = isRecord(item.tag) ? item.tag : {};
      if (flag(tags.unlist) === true) continue;
      const status = tag(item.status);
      unlistedOut.push({ id, normal: status === undefined || STATUS_NORMAL.has(String(status).toLowerCase()) });
    }
  }
  const normal = unlistedOut.filter((item) => item.normal);
  return (normal.length > 0 ? normal : unlistedOut).map((item) => item.id);
}

const TRAFFIC_L1 = ["product_card", "live", "video", "affiliate"] as const;
const TRAFFIC_L2 = new Set([
  "search",
  "recommendation",
  "my_purchase",
  "shopping_cart",
  "shop",
  "promotion",
  "others",
]);
const TRAFFIC_METRICS = [
  "sales",
  "orders",
  "units",
  "buyers",
  "product_impressions",
  "unique_product_impressions",
  "product_clicks",
  "unique_product_clicks",
] as const;

/** One source row's numbers (ratios and pct_diff are dropped); undefined when it carries none. */
function trafficMetrics(source: unknown): Row | undefined {
  if (!isRecord(source)) return undefined;
  const row: Row = {};
  for (const key of TRAFFIC_METRICS) put(row, key, nonNeg(source[key]));
  return Object.keys(row).length > 0 ? row : undefined;
}

const allZero = (metrics: Row) => Object.values(metrics).every((v) => v === 0);

/** `psd_label_search` → `search` (the label as the contract names it); undefined when not a source label. */
function l2Of(source: unknown): string | undefined {
  if (typeof source !== "string") return undefined;
  const name = source.startsWith("psd_label_") ? source.slice("psd_label_".length) : source;
  return TRAFFIC_L2.has(name) ? name : undefined;
}

/**
 * traffic/details answers (one per item per day) → one `item_traffic_sources` post per day:
 * a row per (item, l1 stream, l2 source or "total"), numbers only. Level-2 labels the contract
 * does not name are skipped. All-zero rows of the live / video / affiliate streams are not sent
 * (the product-card rows always are); the answer is aggregate numbers per product, no buyer data.
 */
export function mapItemTraffic(responses: ReaderResponse[]): Mapped[] {
  const days = [
    ...new Set(responses.filter((r) => r.endpoint === "traffic_details").map((r) => r.day).filter((d): d is string => typeof d === "string")),
  ].sort();
  const posts: Mapped[] = [];
  for (const day of days) {
    const issues = { unexpected: [] as string[], missing: [] as string[] };
    const rows: Row[] = [];
    const seen = new Set<string>();
    for (const response of dataResponses(responses.filter((r) => r.day === day), "traffic_details")) {
      const itemId = digits(response.itemId);
      if (itemId === undefined || seen.has(itemId)) continue;
      seen.add(itemId);
      const result = isRecord(response.body) && isRecord(response.body.result) ? response.body.result : null;
      const card = result && isRecord(result.product_card) ? result.product_card : null;
      if (!card || !isRecord(card.total)) {
        if (!issues.missing.includes("result.product_card.total")) issues.missing.push("result.product_card.total");
        continue;
      }
      for (const l1 of TRAFFIC_L1) {
        const block = result?.[l1];
        if (!isRecord(block)) continue;
        const sources: [string, unknown][] = [["total", block.total]];
        if (Array.isArray(block.breakdown)) {
          for (const entry of block.breakdown) {
            const l2 = isRecord(entry) ? l2Of(entry.source) : undefined;
            if (l2 !== undefined) sources.push([l2, entry]);
          }
        }
        const done = new Set<string>();
        for (const [l2, source] of sources) {
          const metrics = trafficMetrics(source);
          if (!metrics || done.has(l2) || (l1 !== "product_card" && allZero(metrics))) continue;
          done.add(l2);
          rows.push({ date: day, item_id: itemId, l1, l2, ...metrics });
        }
      }
    }
    const drift = driftOf(issues.unexpected, issues.missing);
    posts.push({
      dataset: "item_traffic_sources",
      endpoint: "product/traffic/details",
      date: day,
      orderType: "confirmed",
      granularity: "day",
      rows: drift ? [] : rows,
      drift,
    });
  }
  return posts;
}

/** The days of an item_traffic job for which EVERY item was read (a day cut short is read again). */
export function completedTrafficDays(job: ReaderJob, responses: ReaderResponse[]): string[] {
  const ids = job.itemIds ?? [];
  return (job.days ?? []).filter((day) => {
    const ok = new Set(
      dataResponses(responses.filter((r) => r.day === day), "traffic_details").map((r) => r.itemId),
    );
    return ids.length > 0 && ids.every((id) => ok.has(id));
  });
}

// -- ads -----------------------------------------------------------------------------------

const AD_COUNTS = [
  "impression",
  "click",
  "product_impression",
  "product_click",
  "reach",
  "page_views",
  "unique_visitors",
  "checkout",
  "atc",
  "broad_order",
  "direct_order",
] as const;
const AD_RATIOS = ["ctr", "broad_roi", "broad_cir", "direct_roi", "direct_cir", "product_ctr", "avg_rank", "sov"] as const;
const AD_MONEY = ["cost", "cpc", "cpm", "broad_gmv", "direct_gmv", "voucher_amount", "voucher_sales"] as const;
const AD_REPORT_KNOWN = new Set<string>([...AD_COUNTS, ...AD_RATIOS, ...AD_MONEY]);

function adRow(day: string, entry: Record<string, unknown>, drift: { missing: string[]; unexpected: string[] }): Row | null {
  const campaign = isRecord(entry.campaign) ? entry.campaign : {};
  const id = digits(campaign.campaign_id);
  if (id === undefined) {
    if (!drift.missing.includes("entry.campaign.campaign_id")) drift.missing.push("entry.campaign.campaign_id");
    return null;
  }
  const divisor = MONEY_DIVISOR.ads;
  const row: Row = { date: day, campaign_id: id };
  put(row, "campaign_name", text(entry.title, 255));
  put(row, "ad_type", tag(entry.type));
  put(row, "ad_subtype", tag(entry.subtype));
  put(row, "state", tag(entry.state));
  put(row, "daily_budget", money(campaign.daily_budget, divisor));
  put(row, "total_budget", money(campaign.total_budget, divisor));
  put(row, "roi_two_target", nonNeg(campaign.roi_two_target));
  const report = isRecord(entry.report) ? entry.report : {};
  for (const key of AD_COUNTS) put(row, key, nonNeg(report[key]));
  for (const key of AD_RATIOS) put(row, key, nonNeg(report[key]));
  for (const key of AD_MONEY) put(row, key, money(report[key], divisor));
  const extra: Row = {};
  for (const [key, value] of Object.entries(report)) {
    if (AD_REPORT_KNOWN.has(key) || !/^[A-Za-z0-9_.-]{1,64}$/.test(key)) continue;
    const n = nonNeg(value);
    if (n !== undefined && Object.keys(extra).length < 20) extra[key] = n;
  }
  if (Object.keys(extra).length) row.extra = extra;
  const budget = nonNeg(campaign.daily_budget) ?? 0;
  const cost = nonNeg(report.cost) ?? 0;
  if (Math.max(budget, cost) / divisor > MAX_PLAUSIBLE_AD_VND) {
    if (!drift.unexpected.includes("ads:money_scale")) drift.unexpected.push("ads:money_scale");
  }
  return row;
}

/** The ROAS target in force on a day: the last `roi_target_setting.value` of the day's graph. */
export function roasTarget(body: unknown): { value: number; coldStart?: boolean } | null {
  const found = findList(payloadOf(body), (o) => "roi_target_setting" in o);
  let result: { value: number; coldStart?: boolean } | null = null;
  for (const point of found?.list ?? []) {
    const setting = point.roi_target_setting;
    if (!isRecord(setting)) continue;
    const value = nonNeg(setting.value);
    if (value === undefined || value <= 0) continue;
    result = { value, coldStart: flag(setting.is_cold_start) };
  }
  return result;
}

export function mapAdsDaily(responses: ReaderResponse[]): Mapped[] {
  const days = [...new Set(responses.map((r) => r.day).filter((d): d is string => typeof d === "string"))].sort();
  const posts: Mapped[] = [];
  for (const day of days) {
    const issues = { unexpected: [] as string[], missing: [] as string[] };
    const rows: Row[] = [];
    const seen = new Set<string>();
    const homes = dataResponses(responses.filter((r) => r.day === day), "ads_homepage");
    for (const response of homes) {
      const found = findList(payloadOf(response.body), isAdsEntry);
      for (const entry of found?.list ?? []) {
        const row = adRow(day, entry, issues);
        if (row && !seen.has(row.campaign_id as string)) {
          seen.add(row.campaign_id as string);
          rows.push(row);
        }
      }
    }
    for (const response of dataResponses(responses.filter((r) => r.day === day), "ads_time_graph")) {
      const target = roasTarget(response.body);
      if (target) {
        const row: Row = { date: day, roi_target: target.value };
        put(row, "roi_target_cold_start", target.coldStart);
        rows.push(row);
      }
    }
    const usePaid = responses.some((r) => r.day === day && r.usePaidGmv === true);
    const drift = driftOf(issues.unexpected, issues.missing);
    posts.push({
      dataset: "ads_campaign_daily",
      endpoint: "homepage/query",
      date: day,
      orderType: usePaid ? "paid" : "placed",
      granularity: "day",
      rows: drift ? [] : rows,
      drift,
    });
  }
  return posts;
}

// -- vouchers ------------------------------------------------------------------------------

export function mapVoucherList(responses: ReaderResponse[], capturedAt: number): Mapped {
  const date = todayOf(capturedAt);
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const rows: Row[] = [];
  const seen = new Set<string>();
  const divisor = MONEY_DIVISOR.vouchers;
  for (const response of dataResponses(responses, "voucher_list")) {
    const found = findList(payloadOf(response.body), isVoucher);
    for (const voucher of found?.list ?? []) {
      const id = digits(voucher.voucher_id);
      const name = text(voucher.name, 255);
      const starts = wallClock(voucher.start_time);
      if (id === undefined || name === undefined || starts === undefined) {
        const key = id === undefined ? "voucher_id" : name === undefined ? "name" : "start_time";
        if (!issues.missing.includes(`vouchers[].${key}`)) issues.missing.push(`vouchers[].${key}`);
        continue;
      }
      if (seen.has(id)) continue;
      seen.add(id);
      const rule = isRecord(voucher.rule) ? voucher.rule : {};
      const row: Row = { voucher_id: id, program_name: name, starts_at: starts };
      put(row, "voucher_code", text(voucher.voucher_code, 64));
      put(row, "ends_at", wallClock(voucher.end_time));
      const status = text(voucher.fe_status, 64) ?? (tag(voucher.status) === undefined ? undefined : String(tag(voucher.status)));
      put(row, "status", status);
      const amount = money(voucher.value, divisor);
      put(row, "discount_amount", amount !== undefined && amount > 0 ? amount : undefined);
      const percent = nonNeg(voucher.discount);
      put(row, "discount_percent", percent !== undefined && percent > 0 && percent <= 100 ? percent : undefined);
      const cap = money(voucher.max_value, divisor);
      put(row, "max_value", cap !== undefined && cap > 0 ? cap : undefined);
      put(row, "min_spend", money(voucher.min_price, divisor));
      put(row, "usage_limit", nonNeg(voucher.usage_limit));
      put(row, "current_usage", nonNeg(voucher.current_usage));
      put(row, "distributed_count", nonNeg(voucher.distributed_count));
      put(row, "usage_limit_per_user", nonNeg(rule.usage_limit_per_user));
      const asInt = (v: unknown) => {
        const n = num(v);
        return n !== undefined && Number.isInteger(n) ? n : undefined;
      };
      put(row, "use_type", asInt(voucher.use_type));
      put(row, "reward_type", asInt(rule.reward_type));
      put(row, "purpose", asInt(rule.purpose));
      put(row, "is_seller_absorbed", flag(rule.is_seller_absorbed));
      if (Array.isArray(rule.items)) {
        row.item_count = rule.items.length;
        row.item_scope = rule.items.length > 0 ? "items" : "shop";
      }
      rows.push(row);
      const biggest = Math.max(nonNeg(voucher.value) ?? 0, nonNeg(voucher.max_value) ?? 0, nonNeg(voucher.min_price) ?? 0);
      if (biggest / divisor > MAX_PLAUSIBLE_PRICE_VND && !issues.unexpected.includes("vouchers:money_scale")) {
        issues.unexpected.push("vouchers:money_scale");
      }
    }
  }
  const drift = driftOf(issues.unexpected, issues.missing);
  return {
    dataset: "voucher_settings",
    endpoint: "voucher/list",
    date,
    orderType: null,
    granularity: "period",
    rows: drift ? [] : rows,
    drift,
  };
}

// -- account health ------------------------------------------------------------------------

/** The first number in a display value ("92,5%", "3 ngày"); undefined when there is none. */
export function numberIn(value: unknown): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (typeof value !== "string") return undefined;
  const found = /-?\d+(?:[.,]\d+)?/.exec(value);
  if (!found) return undefined;
  const n = Number(found[0].replace(",", "."));
  return Number.isFinite(n) ? n : undefined;
}

/** pass / fail from `compare_result` when it says so unambiguously (booleans, clear words). */
export function passedOf(value: unknown): boolean | undefined {
  if (typeof value === "boolean") return value;
  if (typeof value !== "string") return undefined;
  const lower = value.toLowerCase();
  if (/not|fail|below|unmet|miss|bad|worse/.test(lower)) return false;
  if (/pass|meet|ok|good|achiev|reach/.test(lower)) return true;
  return undefined;
}

const NAME_KEYS = ["metric_name", "name", "title", "display_name", "metric_title"] as const;

export function mapShopHealth(responses: ReaderResponse[], capturedAt: number): Mapped {
  const date = todayOf(capturedAt);
  const issues = { unexpected: [] as string[], missing: [] as string[] };
  const rows: Row[] = [];

  const overview = dataResponses(responses, "health_overview")[0];
  const summary = isRecord(payloadOf(overview?.body)) ? (payloadOf(overview?.body) as Record<string, unknown>) : null;
  if (summary) {
    const row: Row = { date };
    put(row, "failed_metric_count", nonNeg(summary.failed_metric_count));
    put(row, "penalty_point", nonNeg(summary.penalty_point));
    put(row, "performance_rating", tag(summary.performance_rating));
    if (Object.keys(row).length > 1) rows.push(row);
  }

  const labels = new Map<string, string>();
  for (const response of dataResponses(responses, "health_metric_configs")) {
    const found = findList(payloadOf(response.body), (o) => digits(o.metric_id) !== undefined);
    for (const config of found?.list ?? []) {
      const id = digits(config.metric_id);
      const key = NAME_KEYS.find((k) => typeof config[k] === "string");
      if (id !== undefined && key) labels.set(id, (config[key] as string).trim().slice(0, 255));
    }
  }

  for (const response of dataResponses(responses, "health_metric_list")) {
    const found = findList(payloadOf(response.body), (o) => "metric_id" in o);
    if (!found) {
      issues.missing.push("metric_list");
      continue;
    }
    const seen = new Set<string>();
    for (const metric of found.list) {
      const id = digits(metric.metric_id);
      if (id === undefined) {
        if (!issues.missing.includes("metric_list[].metric_id")) issues.missing.push("metric_list[].metric_id");
        continue;
      }
      if (seen.has(id)) continue;
      seen.add(id);
      const row: Row = { date, metric_id: id };
      put(row, "label", labels.get(id));
      const display = typeof metric.display_value === "number" ? String(metric.display_value) : text(metric.display_value, 64);
      put(row, "display_value", display);
      put(row, "value", numberIn(metric.display_value));
      const targetDisplay = typeof metric.target_value === "number" ? String(metric.target_value) : text(metric.target_value, 64);
      put(row, "target_display", targetDisplay);
      put(row, "target", numberIn(metric.target_value));
      put(row, "compare_result", tag(metric.compare_result));
      put(row, "passed", passedOf(metric.compare_result));
      put(row, "metric_tag", tag(metric.metric_tag));
      rows.push(row);
    }
  }
  const drift = driftOf(issues.unexpected, issues.missing);
  return {
    dataset: "shop_health_daily",
    endpoint: "accounthealth/metric_list",
    date,
    orderType: null,
    granularity: "day",
    rows: drift ? [] : rows,
    drift,
  };
}

// -- one job -------------------------------------------------------------------------------

export function mapReaderJob(job: ReaderJob, responses: ReaderResponse[], capturedAt: number): Mapped[] {
  switch (job.id) {
    case "products": {
      const { catalog, snapshot } = mapProductList(responses, capturedAt);
      return [catalog, snapshot];
    }
    case "item_traffic":
      return mapItemTraffic(responses);
    case "ads":
      return mapAdsDaily(responses);
    case "vouchers":
      return [mapVoucherList(responses, capturedAt)];
    case "health":
      return [mapShopHealth(responses, capturedAt)];
  }
}
