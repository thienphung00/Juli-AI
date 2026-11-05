// Market search reader, pure parts (P92 B-10): which keywords to read, how to recognise and trim
// the public search page's own answer, and how its cards map to the `market_search` ingest rows.
//
// Public data only: a card's item/shop ids, name, shop name, prices, sold counts, rating, image id.
// Nothing else leaves the page (trimSearchBody keeps ONLY those fields), no buyer data exists on
// a search card. Field names and units are recon GUESSES (docs/integrations/shopee/
// market-search-recon.md, "to verify on a real capture"); a card list that does not look like
// them is DRIFT: the dataset is paused for this extension version and nothing is posted.

import {
  MARKET_MAX_CARDS,
  MARKET_MAX_KEYWORDS_PER_RUN,
  MARKET_MAX_PER_PRODUCT,
  MARKET_MIN_DAYS_BETWEEN_READS,
  MARKET_MIN_PLAUSIBLE_VND,
  MARKET_ORIGIN,
  MARKET_PAGE_PATH,
  MARKET_PRICE_DIVISOR,
  MARKET_SEARCH_PATH,
  MARKET_SORT,
  MAX_PLAUSIBLE_PRICE_VND,
} from "../config";
import type { Mapped, Row } from "./map";
import { gmt7Date } from "./time";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonNeg(value: unknown): number | undefined {
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

// -- the server's keyword list -----------------------------------------------------------------

export interface MarketPlan {
  enabled?: boolean;
  max_per_product?: number;
  products?: { item_id?: string; keywords?: string[] }[];
  due_keywords?: string[];
  last_collected?: Record<string, string>;
}

const fold = (keyword: string) => keyword.normalize("NFC").trim().toLowerCase();

function daysBetween(from: string, to: string): number {
  return Math.floor((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000);
}

/**
 * The keywords to read today: each product's first 1-3 keywords (de-duplicated across products),
 * only those the server says are due (when it says) and that this browser has not read in the
 * last MARKET_MIN_DAYS_BETWEEN_READS days, at most MARKET_MAX_KEYWORDS_PER_RUN.
 */
export function pickKeywords(plan: MarketPlan, lastRead: Record<string, string>, today: string): string[] {
  if (plan.enabled !== true) return [];
  const perProduct = Math.max(1, Math.min(Number(plan.max_per_product) || MARKET_MAX_PER_PRODUCT, MARKET_MAX_PER_PRODUCT));
  const due = Array.isArray(plan.due_keywords) ? new Set(plan.due_keywords.map(fold)) : null;
  const local = new Map(Object.entries(lastRead).map(([k, day]) => [fold(k), day]));
  const picked: string[] = [];
  const seen = new Set<string>();
  for (const product of plan.products ?? []) {
    for (const raw of (product.keywords ?? []).slice(0, perProduct)) {
      const keyword = typeof raw === "string" ? raw.trim() : "";
      const key = fold(keyword);
      if (!keyword || keyword.length > 200 || seen.has(key)) continue;
      seen.add(key);
      if (due && !due.has(key)) continue;
      const read = local.get(key);
      if (read !== undefined && daysBetween(read, today) < MARKET_MIN_DAYS_BETWEEN_READS) continue;
      picked.push(keyword);
      if (picked.length >= MARKET_MAX_KEYWORDS_PER_RUN) return picked;
    }
  }
  return picked;
}

/** The public search page for a keyword (the only URL the market run opens). */
export function searchPageUrl(keyword: string): string {
  return `${MARKET_ORIGIN}${MARKET_PAGE_PATH}?keyword=${encodeURIComponent(keyword)}`;
}

/** Whether a URL is the search page's own search-items call; the keyword it was for, page 1 only. */
export function searchCall(rawUrl: string): { keyword: string } | null {
  try {
    const url = new URL(rawUrl, MARKET_ORIGIN);
    if (url.origin !== MARKET_ORIGIN || url.pathname.replace(/\/+$/, "") !== MARKET_SEARCH_PATH) return null;
    const newest = url.searchParams.get("newest");
    if (newest !== null && Number(newest) !== 0) return null; // page 2+ (offset): not read
    const keyword = url.searchParams.get("keyword");
    return keyword ? { keyword } : null;
  } catch {
    return null;
  }
}

/** The keyword in the tab's own address (`/search?keyword=...`), to match the answer to the job. */
export function sameKeyword(a: string, b: string): boolean {
  return fold(a) === fold(b);
}

/** Shopee's anti-fraud refusal code (as in reader.ts): a verification is due. */
const ANTI_FRAUD_CODE = 90309999;

/** The tab's path is a login / verification page. */
export function marketBlockedPath(pathname: string): "login" | "captcha" | null {
  if (/^\/(verify|captcha|security|anti[-_]?bot)/i.test(pathname) || /\/(verify|captcha)\//i.test(pathname)) return "captcha";
  if (/^\/buyer\/(login|signup)|^\/(login|signin)/i.test(pathname)) return "login";
  return null;
}

/** HTTP status + body of the search answer -> ok | captcha | error. A login wall is a path, not an answer. */
export function classifyAnswer(status: number, body: unknown): "ok" | "captcha" | "error" {
  if (status === 403 || status === 429) return "captcha";
  if (status < 200 || status >= 300) return "error";
  if (!isRecord(body)) return "error";
  const error = body.error;
  if (error === ANTI_FRAUD_CODE) return "captcha";
  if (error !== undefined && error !== null && error !== 0) return "error";
  return "ok";
}

// -- the answer ----------------------------------------------------------------------------------

/** The card list of the answer: `items[]` (each `{ item_basic: {...}, adsid?, ... }` or flat). */
function cardsOf(body: unknown): Record<string, unknown>[] | null {
  if (!isRecord(body)) return null;
  const items = body.items ?? (isRecord(body.data) ? body.data.items : undefined);
  return Array.isArray(items) && items.every(isRecord) ? (items as Record<string, unknown>[]) : null;
}

const basicOf = (card: Record<string, unknown>): Record<string, unknown> =>
  isRecord(card.item_basic) ? card.item_basic : card;

/** An ad card carries an ad id / campaign / keyword next to (not inside) the item (to verify). */
function isAd(card: Record<string, unknown>): boolean {
  const basic = basicOf(card);
  const marked = (v: unknown) => v !== undefined && v !== null && v !== 0 && v !== "" && v !== false;
  return [card.adsid, card.campaignid, card.ads_keyword, card.ad_keyword, basic.adsid, basic.is_ad].some(marked);
}

const BASIC_KEYS = [
  "itemid",
  "shopid",
  "name",
  "shop_name",
  "price",
  "price_min",
  "price_max",
  "price_before_discount",
  "raw_discount",
  "historical_sold",
  "sold",
  "image",
] as const;

/**
 * The page's answer cut down to the public card fields the mapper reads, so nothing else (tracking
 * ids, user fields, recommendations) ever leaves the page hook. Pure; the hook calls it.
 */
export function trimSearchBody(body: unknown): unknown {
  if (!isRecord(body)) return null;
  const cards = cardsOf(body);
  const out: Record<string, unknown> = { error: body.error ?? null };
  if (cards === null) return out;
  out.items = cards.slice(0, MARKET_MAX_CARDS).map((card) => {
    const basic = basicOf(card);
    const kept: Record<string, unknown> = {};
    for (const key of BASIC_KEYS) if (basic[key] !== undefined) kept[key] = basic[key];
    if (isRecord(basic.item_rating) && basic.item_rating.rating_star !== undefined) {
      kept.item_rating = { rating_star: basic.item_rating.rating_star };
    }
    if (isRecord(basic.item_card_display_sold_count)) {
      const sold = basic.item_card_display_sold_count;
      kept.item_card_display_sold_count = {
        monthly_sold_count: sold.monthly_sold_count,
        display_sold_count_text: typeof sold.display_sold_count_text === "string" ? sold.display_sold_count_text : undefined,
      };
    }
    return { item_basic: kept, ...(isAd(card) ? { adsid: 1 } : {}) };
  });
  return out;
}

const vnd = (value: unknown): number | undefined => {
  const n = nonNeg(value);
  return n === undefined ? undefined : Math.round(n / MARKET_PRICE_DIVISOR);
};

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? (sorted[mid] as number) : ((sorted[mid - 1] as number) + (sorted[mid] as number)) / 2;
}

/** The ingest post for one keyword's page-1 answer. `rows` is empty with `drift` set when it is not trusted. */
export function mapMarketSearch(keyword: string, body: unknown, capturedAt: number): Mapped {
  const date = gmt7Date(Math.floor(capturedAt / 1000));
  const missing: string[] = [];
  const unexpected: string[] = [];
  const rows: Row[] = [];
  const cards = cardsOf(body);
  if (cards === null) missing.push("items");
  for (const [index, card] of (cards ?? []).slice(0, MARKET_MAX_CARDS).entries()) {
    const basic = basicOf(card);
    const itemId = digits(basic.itemid);
    const name = text(basic.name, 500);
    const price = vnd(basic.price) ?? vnd(basic.price_min);
    for (const [field, value] of [["itemid", itemId], ["name", name], ["price", price]] as const) {
      if (value === undefined && !missing.includes(`items[].${field}`)) missing.push(`items[].${field}`);
    }
    if (itemId === undefined || name === undefined || price === undefined) continue;
    const row: Row = { keyword, sort: MARKET_SORT, page: 1, pos: index + 1, is_ad: isAd(card), item_id: itemId, title: name, price };
    const put = (key: string, value: unknown) => {
      if (value !== undefined) row[key] = value;
    };
    put("shop_id", digits(basic.shopid));
    put("shop_title", text(basic.shop_name, 120));
    const min = vnd(basic.price_min);
    const max = vnd(basic.price_max);
    if (min !== undefined && max !== undefined && max > min) {
      put("price_min", min);
      put("price_max", max);
    }
    const before = vnd(basic.price_before_discount);
    if (before !== undefined && before > price) {
      put("price_before_discount", before);
      put("discount_pct", Math.min(100, Math.round(((before - price) / before) * 1000) / 10));
    }
    const raw = nonNeg(basic.raw_discount);
    if (row.discount_pct === undefined && raw !== undefined && raw > 0 && raw <= 100) put("discount_pct", raw);
    const rating = isRecord(basic.item_rating) ? nonNeg(basic.item_rating.rating_star) : undefined;
    if (rating !== undefined && rating <= 5) put("rating", Math.round(rating * 100) / 100);
    const display = isRecord(basic.item_card_display_sold_count) ? basic.item_card_display_sold_count : undefined;
    put("sold_monthly", nonNeg(display?.monthly_sold_count) ?? nonNeg(basic.sold));
    put("sold_lifetime", nonNeg(basic.historical_sold));
    put("sold_text", text(display?.display_sold_count_text, 120));
    put("image_id", text(basic.image, 100));
    rows.push(row);
  }
  if (rows.length > 0) {
    const prices = rows.map((r) => r.price as number);
    if (prices.some((p) => p > MAX_PLAUSIBLE_PRICE_VND) || median(prices) < MARKET_MIN_PLAUSIBLE_VND) {
      unexpected.push("market:price_scale");
    }
  }
  const drift = missing.length || unexpected.length ? { unexpected, missing } : null;
  return {
    dataset: "market_search",
    endpoint: "search/search_items",
    date,
    orderType: null,
    granularity: "period",
    rows: drift ? [] : rows,
    drift,
  };
}
