// The page readers' request side (pure, unit-tested with injected fetch / sleep / clock):
// given the request templates the page hook has learned from the page's OWN calls, replay them
// for one reader job (product list pages, one ads day, voucher pages, account health) at
// ≥ 2 s + jitter per request, and stop on a CAPTCHA / login wall.
//
// Read-only: every request is a GET, or one of the page's own POST *queries* (its report
// endpoints) with only a day / page number changed. Nothing here creates, applies or saves.

import {
  ADS_MAX_ROWS_PER_DAY,
  AFFILIATE_MAX_ROWS,
  AFFILIATE_PAGE_SIZE_DEFAULT,
  AFFILIATE_WINDOW_DAYS,
  ADS_PAGE_LIMIT_DEFAULT,
  ADS_HISTORY_DAY_COST,
  ORDER_DETAIL_MAX_PER_RUN,
  ORDER_LIST_MAX_PAGES_PER_RUN,
  ORDER_LIST_MIN_PAGES,
  ORDER_LIST_PAGE_GAP_JITTER_MS,
  ORDER_LIST_PAGE_GAP_MS,
  PRODUCT_MAX_PAGES,
  TRAFFIC_MAX_CONSECUTIVE_ERRORS,
  TRAFFIC_MAX_REQUESTS_PER_JOB,
  READER_POLL_MS,
  READER_TEMPLATE_WAIT_MS,
  type ReaderId,
  VOUCHER_MAX_ROWS,
  PRODUCT_PERIOD_DAYS,
  PRODUCT_PERIOD_MAX_PAGES,
  PRODUCT_PERIOD_PAGE_SIZE,
  VOUCHER_PAGE_LIMIT_DEFAULT,
  COMBO_DETAIL_MAX,
  COMBO_MAX_ROWS,
  COMBO_PAGE_LIMIT_DEFAULT,
} from "./config";
import { isDatacenterPath, isMydataPath } from "./config";
import { isReadOnlyOrderDetailPath, isReadOnlyOrderPath, isReadOnlyPasPath, READER_ENDPOINTS, READER_PAGES, type ReaderEndpoint } from "./endpoints";
import { isNoCampaign } from "./promotion-map";
import { cardOrdersWithoutSku, incomeNotFinal, type PageItem, pageIncomeFinal, plainLabel, trimOrderCards, trimOrderDetail, trimOrderIndex, withPageSkus, withUnresolvedSkus } from "./orders-map";
import type { Pacer } from "./runner";
import { buildBackfillDayPlan } from "./sync";
import { gmt7Date, gmt7DateStart, lastFinishedDays } from "../../core/time";

/** What the hook learned from the page's own call to an endpoint (kept in page memory only). */
export interface Template {
  /** Query params without the session params. */
  query: Record<string, string>;
  /** The page's JSON request body (POST endpoints). */
  body?: unknown;
  /** The page's own request headers (replayed as they are, minus a deny list). */
  headers?: Record<string, string>;
  /** The page's last response body (kept only for `campaign_info`, whose request is not replayed). */
  lastResponse?: unknown;
  /** 0.3.26: the HTTP status of the page's own last call when it was not 2xx (captured endpoints only). */
  lastStatus?: number;
  /** 0.3.26: the Shopee error code of that refused answer, when it had one (metadata only). */
  lastCode?: string;
}

export interface ReaderJob {
  id: ReaderId;
  /** Ads: the finished GMT+7 days to read, one request set per day. */
  days?: string[];
  /** item_traffic: the item ids to read for each day. */
  itemIds?: string[];
  /** ads_detail: the ongoing campaigns to read; the first is the page the scheduler opened. */
  campaignIds?: string[];
  /** ads_detail: per campaign, "manual" or "mpd" (which edit page it has). */
  campaignKinds?: string[];
  /** ads_products: per campaign, its title (the key the daily ads rows use); "" = unknown. */
  campaignNames?: string[];
  /** order_income: the completed orders to read; the first is the order page the scheduler opened. */
  orderIds?: string[];
  /** order_income: per order, the order number that is hashed (parallel to `orderIds`; "" = unknown). */
  orderSns?: string[];
  /** order_income (0.3.32): per order, false when only its lines are read (not completed yet: no income). */
  incomeFor?: boolean[];
  /** order_income (0.3.32): per order, its trimmed get_one_order answer when a line named no SKU (else null). */
  fixBodies?: (unknown | null)[];
  /** order_income (0.3.32): per order, this is its last page read for its lines (then "unresolved_item"). */
  fixLast?: boolean[];
  /** affiliate: older purchase windows to read once (the 6-month history), each ≤ 31 days. */
  history?: ConversionWindow[];
  /** orders (0.3.19): read back until orders placed before this GMT+7 day. */
  sinceDay?: string;
  /** ads (0.3.19): older days of the ads history, newest first, read after `days`. */
  historyDays?: string[];
  /** Requests this job may still send (the shared daily budget's remainder). */
  budget?: number;
}

/** A GMT+7 purchase window of the conversion report, both ends included. */
export interface ConversionWindow {
  start: string;
  end: string;
}

export interface ReaderResponse {
  endpoint: ReaderEndpoint;
  /** The request URL without the session params. */
  url: string;
  /** HTTP status; 0 = network failure; 200 for a response the page itself loaded. */
  status: number;
  /** Parsed JSON body, or null (not JSON: a login page). */
  body: unknown;
  capturedAt: number;
  page?: number;
  day?: string;
  /** item_traffic: the item the request was for. */
  itemId?: string;
  /** ads_products: the campaign's title, when the scheduler knew it. */
  campaignName?: string;
  /** ads_detail: the campaign the answer is about. */
  campaignId?: string;
  /** order_income: the order the answer is about (raw id: hashed in the service worker, never posted). */
  orderId?: string;
  /** order_income: that order's number (the id that is hashed), when the queue knew it. */
  orderSn?: string;
  source: "replay" | "page";
  /** Ads: the request asked for paid (not placed) orders. */
  usePaidGmv?: boolean;
  /** Affiliate: the GMT+7 days the answer covers (from the page's own request, or the window asked). */
  period?: { start: string; end: string };
}

export type ReaderStatus =
  | "done"
  | "needs_data_page"
  | "needs_template"
  | "blocked_captcha"
  | "blocked_login"
  /** 0.3.28: Shopee's traffic-check page (/verify/traffic…): every Shopee automation pauses 6 h. */
  | "blocked_traffic_check"
  /** 0.3.25: /datacenter's "enter your Shopee password" dialog (never typed into by the Connector). */
  | "blocked_password_recheck"
  /** HTTP 429 / 403 / a Shopee message that says "too many requests": stops every reader. */
  | "blocked_rate"
  /** The shared daily request budget is spent: the job stops, the rest waits for tomorrow. */
  | "budget_spent"
  /** 0.3.26: the account may not open this page (Tài chính / income): this page only, never retried today. */
  | "blocked_no_permission"
  | "error";

export interface ReaderOutcome {
  status: ReaderStatus;
  responses: ReaderResponse[];
  detail?: string;
}

export interface ReaderRequest {
  endpoint: ReaderEndpoint;
  method: "GET" | "POST";
  /** With the session params. */
  url: string;
  publicUrl: string;
  headers: Record<string, string>;
  body?: string;
}

export interface FetchedReaderResponse {
  status: number;
  text(): Promise<string>;
}

/** One order card of the list page (0.3.20): the id of its link, the order number of its text. */
export interface OrderLink {
  /** The numeric order id of `/portal/sale/order/<id>` (what get_one_order takes). */
  id: string;
  /** "Mã đơn hàng <sn>": the order number (its first 6 characters are the GMT+7 day, YYMMDD). */
  sn?: string;
}

export interface ReaderEnv {
  origin: string;
  pacer: Pacer;
  now: () => number;
  session: () => Record<string, string>;
  hasSession: () => boolean;
  template: (endpoint: ReaderEndpoint) => Template | undefined;
  /** Poll `condition` until true or `ms` have passed; true when it became true. */
  waitFor: (condition: () => boolean, ms: number) => Promise<boolean>;
  fetch: (request: ReaderRequest) => Promise<FetchedReaderResponse>;
  /** A CAPTCHA overlay / verification page is showing in this tab. */
  captchaVisible?: () => boolean;
  /** Seller Centre's "enter your Shopee password" re-confirmation modal is showing (never typed into). */
  passwordModalVisible?: () => boolean;
  /** Request headers the page sent on its own /api/mydata calls (a template for endpoints it never called). */
  mydataHeaders?: () => Record<string, string> | undefined;
  /** The tab's current path (a client-side redirect to a login or verification page). */
  pathname?: () => string;
  /** Requests left in this job's allowance; every request sent takes one (no budget = unlimited). */
  budget?: { left: number };
  /** A real wait (order-list pages are spaced 20-45 s apart); absent in tests that do not care. */
  pause?: (ms: number) => Promise<void>;
  random?: () => number;
  /** orders (0.3.20): the order cards the list page shows now (read from its DOM). */
  orderLinks?: () => OrderLink[];
  /** orders (0.3.20): the list page shows its "no orders" state. */
  orderListEmpty?: () => boolean;
  /** orders (0.3.28): the list's pager shows more pages (read only: the Connector never presses it). */
  moreOrderPages?: () => boolean;
  /** 0.3.26: the page shows Seller Centre's "no permission" page or message (a sub-account without the right). */
  permissionDeniedVisible?: () => boolean;
  /** Phân tích Nội dung (0.3.32): its own count node says "0 Nội dung" (or its table's empty state), no error banner (content-dom.ts). */
  contentEmptyVisible?: () => boolean;
  /** order page (0.3.32): the "Doanh thu" rows it shows, `{name, amount}` (order-page-dom.ts). */
  orderPageIncome?: () => { name: string; amount: number }[];
  /** batch-1124-a S1: the order page's buyer-payment voucher rows (Shopee Voucher, Mã giảm giá của Shop). */
  orderPageBuyer?: () => { name: string; amount: number }[];
  /** order page (0.3.32): its product lines ("Phân loại", "SKU phân loại", line total). */
  orderPageItems?: () => PageItem[];
}

// -- request building ----------------------------------------------------------------------

const DENIED_HEADERS = new Set([
  "cookie",
  "host",
  "content-length",
  "origin",
  "referer",
  "user-agent",
  "accept-encoding",
  "connection",
  "priority",
]);

export function replayHeaders(source: Record<string, string> | undefined): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const [name, value] of Object.entries(source ?? {})) {
    const lower = name.toLowerCase();
    if (DENIED_HEADERS.has(lower) || lower.startsWith("sec-")) continue;
    headers[name] = value;
  }
  return headers;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * One request from the page's template with only `overrides` changed. GET: the template's
 * query plus overrides. POST: the template's query, and its JSON body plus overrides.
 */
export function buildReaderRequest(
  origin: string,
  endpoint: ReaderEndpoint,
  template: Template | undefined,
  overrides: { query?: Record<string, string>; body?: Record<string, unknown> },
  session: Record<string, string>,
  fallbackBody?: Record<string, unknown>,
): ReaderRequest {
  const spec = READER_ENDPOINTS[endpoint];
  const query = { ...(template?.query ?? {}), ...(overrides.query ?? {}) };
  const publicUrl = `${origin}${spec.path}${Object.keys(query).length ? `?${new URLSearchParams(query).toString()}` : ""}`;
  const url = `${origin}${spec.path}?${new URLSearchParams({ ...query, ...session }).toString()}`;
  const headers = replayHeaders(template?.headers);
  if (spec.method === "GET") {
    return { endpoint, method: "GET", url, publicUrl, headers };
  }
  const base = isRecord(template?.body) ? template.body : (fallbackBody ?? {});
  headers["Content-Type"] = "application/json";
  return {
    endpoint,
    method: "POST",
    url,
    publicUrl,
    headers,
    body: JSON.stringify({ ...base, ...(overrides.body ?? {}) }),
  };
}

// -- reading a response --------------------------------------------------------------------

/** The data part of a Seller Centre answer: `data`, else `result`, else the body itself. */
export function payloadOf(body: unknown): unknown {
  if (!isRecord(body)) return null;
  if (body.data !== undefined && body.data !== null) return body.data;
  if (body.result !== undefined && body.result !== null) return body.result;
  return body;
}

type Verdict = "ok" | "login" | "captcha" | "rate" | "error";

/** Shopee wording (or code) that means "slow down": it stops every reader, like a CAPTCHA. */
const RATE_WORDS = /rate.?limit|too many|frequen|try again later|quá nhiều|thử lại sau|tần suất|thao tác quá/i;

/** Shopee's anti-fraud refusal: HTTP 403 with this error code (a CAPTCHA / verification is due). */
const ANTI_FRAUD_CODE = 90309999;
const LOGIN_WORDS = /login|logged|sign.?in|session|auth|expired/i;

export function classify(status: number, body: unknown): Verdict {
  if (status === 401) return "login";
  if (status === 429) return "rate";
  if (status === 403) {
    // The anti-fraud code is a verification page; any other 403 is treated as a rate stop too
    // (P97: nothing is retried against a refusal).
    if (isRecord(body) && body.error !== undefined && Number(body.error) !== ANTI_FRAUD_CODE) return "rate";
    return "captcha";
  }
  if (status < 200 || status >= 300) return "error";
  if (!isRecord(body)) return "login"; // a login page instead of JSON
  const code = body.code ?? body.error;
  if (code === undefined || code === 0 || code === "0" || code === null) return "ok";
  if (isNoCampaign(body)) return "ok"; // F6.4: a day with no flash sale is an empty day
  // 0.3.29: code 10000 ("permission denied" / "not login") is mydata's answer to a call from outside /datacenter/
  if (Number(code) === 10000) return "error";
  const text = `${String(body.msg ?? "")} ${String(body.message ?? "")} ${typeof code === "string" ? code : ""}`;
  if (Number(code) === 429 || RATE_WORDS.test(text)) return "rate";
  return LOGIN_WORDS.test(text) ? "login" : "error";
}

/** Shopee wording that means "this account may not open this" (a sub-account without the right). */
const PERMISSION_WORDS = /permission|không có quyền|khong co quyen|quyền truy cập|quyen truy cap|forbidden/i;

/** The Shopee error code of an answer, as a short metadata token (no message text), or "". */
export function answerCode(body: unknown): string {
  if (!isRecord(body)) return "";
  const code = body.code ?? body.error;
  if (code === undefined || code === null || code === 0 || code === "0" || code === "") return "";
  return String(code).replace(/[^A-Za-z0-9_-]/g, "").slice(0, 16);
}

/**
 * 0.3.26: an answer to one of OUR requests that says the account has no permission: a refusal
 * (HTTP 403 that is not the anti-fraud verification, or a Shopee error code) whose message says
 * "permission" / "không có quyền". A bare 403 to a replay stays classify's rate stop (P97: every
 * reader stops on a refusal); a 403 on the page's OWN income call is handled in readOrderIncome.
 * Only the income reader asks (Tài chính).
 */
export function isPermissionRefusal(status: number, body: unknown): boolean {
  if (status === 401 || status === 429 || !isRecord(body)) return false;
  if (status === 403 && Number(body.error ?? body.code) === ANTI_FRAUD_CODE) return false;
  if (status !== 403 && answerCode(body) === "") return false;
  return PERMISSION_WORDS.test(`${String(body.msg ?? "")} ${String(body.message ?? "")} ${String(body.error_msg ?? "")}`);
}

/** First array of objects (breadth-first, a few levels deep) whose first element passes `fits`. */
export function findList(
  root: unknown,
  fits: (first: Record<string, unknown>) => boolean,
  depth = 4,
): { list: Record<string, unknown>[]; parent: Record<string, unknown> } | null {
  if (Array.isArray(root) && root.length > 0 && root.every(isRecord) && fits(root[0] as Record<string, unknown>)) {
    return { list: root as Record<string, unknown>[], parent: {} };
  }
  const queue: { node: unknown; level: number }[] = [{ node: root, level: 0 }];
  while (queue.length > 0) {
    const { node, level } = queue.shift() as { node: unknown; level: number };
    if (!isRecord(node)) continue;
    for (const value of Object.values(node)) {
      if (Array.isArray(value) && value.length > 0 && value.every(isRecord) && fits(value[0] as Record<string, unknown>)) {
        return { list: value as Record<string, unknown>[], parent: node };
      }
    }
    if (level < depth) {
      for (const value of Object.values(node)) {
        if (isRecord(value)) queue.push({ node: value, level: level + 1 });
      }
    }
  }
  return null;
}

/** The total a paged answer states (`total`, `page_info.total`, ...), or undefined. */
export function totalOf(body: unknown, parent?: Record<string, unknown>): number | undefined {
  const candidates: unknown[] = [];
  for (const node of [parent, payloadOf(body), body]) {
    if (!isRecord(node)) continue;
    candidates.push(node.total, node.total_count, node.count);
    if (isRecord(node.page_info)) candidates.push(node.page_info.total, node.page_info.total_count);
    if (isRecord(node.pagination)) candidates.push(node.pagination.total);
  }
  for (const value of candidates) {
    const n = typeof value === "string" ? Number(value) : value;
    if (typeof n === "number" && Number.isFinite(n) && n >= 0) return n;
  }
  return undefined;
}

export const isProduct = (o: Record<string, unknown>) =>
  "model_list" in o || "price_detail" in o || ("id" in o && "stock_detail" in o);
export const isAdsEntry = (o: Record<string, unknown>) => isRecord(o.campaign) || isRecord(o.report);
export const isVoucher = (o: Record<string, unknown>) => "voucher_id" in o;
/** 0.3.35: one row of the discount list's Combo tab (`discounts[].bundle_deal`). */
export const isComboEntry = (o: Record<string, unknown>) => isRecord(o.bundle_deal);
/** The discount list's code for a combo (`discount_type`, P-C2 capture). */
export const COMBO_DISCOUNT_TYPE = 3;
/** The list's `time_status` of a combo not ended yet: 1 upcoming (assumed, not seen), 2 running. */
const COMBO_LIVE_STATUSES = new Set([1, 2]);

/** The /datacenter re-confirmation modal's text (any dialog text is passed in). */
export function isPasswordPrompt(text: string): boolean {
  return /vui lòng nhập mật khẩu shopee/i.test(text);
}

/** `path` blocked by a login / verification page (client-side redirect or whole-tab redirect). */
export function blockedPath(pathname: string): "login" | "captcha" | "traffic_check" | null {
  // 0.3.28 (contract R): Shopee's anti-bot page is its own reason (not a login, not a CAPTCHA)
  if (/\/verify\/traffic/i.test(pathname)) return "traffic_check";
  if (/\/(verify|captcha|anti[-_]?bot|security[-_]?check)/i.test(pathname)) return "captcha";
  if (/\/(login|signin|sign[-_]in|account\/sign|seller\/login|authenticate)/i.test(pathname)) return "login";
  return null;
}

// -- running one job -----------------------------------------------------------------------

const fail = (status: ReaderStatus, responses: ReaderResponse[], detail?: string): ReaderOutcome => ({
  status,
  responses,
  ...(detail ? { detail } : {}),
});

class Stop extends Error {
  constructor(readonly outcome: ReaderOutcome) {
    super(outcome.status);
  }
}

/** Send one request (paced), parse it, and stop the job on a login wall / CAPTCHA / error. */
async function send(
  env: ReaderEnv,
  request: ReaderRequest,
  collected: ReaderResponse[],
  extra: Partial<ReaderResponse> = {},
  tolerateError = false,
  permissionAware = false,
): Promise<ReaderResponse> {
  if (env.passwordModalVisible?.()) throw new Stop(fail("blocked_password_recheck", collected, "password_modal"));
  // 0.3.29: a mydata call from a page outside /datacenter/ is answered "not login": never sent
  const pathname = env.pathname?.();
  if (pathname !== undefined && pathname !== "" && isMydataPath(new URL(request.publicUrl).pathname) && !isDatacenterPath(pathname)) {
    throw new Stop(fail("needs_data_page", collected, "not_datacenter"));
  }
  const wall = env.captchaVisible?.() ? "captcha" : blockedPath(env.pathname?.() ?? "");
  if (wall) throw new Stop(fail(wall === "captcha" ? "blocked_captcha" : wall === "traffic_check" ? "blocked_traffic_check" : "blocked_login", collected, "page"));
  // The shared daily budget is checked before EVERY replay.
  if (env.budget) {
    if (env.budget.left <= 0) throw new Stop(fail("budget_spent", collected, request.endpoint));
    env.budget.left -= 1;
  }
  await env.pacer.beforeRequest();
  let status = 0;
  let body: unknown = null;
  try {
    const response = await env.fetch(request);
    status = response.status;
    try {
      body = JSON.parse(await response.text());
    } catch {
      body = null;
    }
  } catch {
    status = 0;
  }
  const result: ReaderResponse = {
    endpoint: request.endpoint,
    url: request.publicUrl,
    status,
    body,
    capturedAt: env.now(),
    source: "replay",
    ...extra,
  };
  collected.push(result);
  if (permissionAware && isPermissionRefusal(status, body)) {
    const code = answerCode(body);
    throw new Stop(fail("blocked_no_permission", collected, `http_${status}${code ? `_code_${code}` : ""}`));
  }
  const verdict = classify(status, body);
  if (verdict === "captcha") throw new Stop(fail("blocked_captcha", collected, `http_${status}`));
  if (verdict === "login") throw new Stop(fail("blocked_login", collected, `http_${status}`));
  if (verdict === "rate") throw new Stop(fail("blocked_rate", collected, `http_${status}`));
  if (verdict === "error" && tolerateError) return result;
  if (verdict === "error") throw new Stop(fail("error", collected, `${request.endpoint}:http_${status}`));
  return result;
}

function pageSizeOf(template: Template, fallback: number): number {
  const n = Number(template.query.page_size ?? template.query.limit);
  return Number.isInteger(n) && n > 0 ? n : fallback;
}

async function waitForPage(env: ReaderEnv, need: ReaderEndpoint[], collected: ReaderResponse[]): Promise<void> {
  // 0.3.22: Phân tích bán hàng's password re-confirmation (or a CAPTCHA) means the page never makes
  // its own calls. Before, shop_totals waited it out and reported needs_template:shop_key_metrics.
  const modal = () => env.passwordModalVisible?.() === true;
  const captcha = () => env.captchaVisible?.() === true;
  const ready = () => env.hasSession() && need.every((endpoint) => env.template(endpoint) !== undefined);
  const settled = await env.waitFor(() => modal() || captcha() || ready(), READER_TEMPLATE_WAIT_MS);
  if (modal()) throw new Stop(fail("blocked_password_recheck", collected, "password_modal"));
  if (captcha()) throw new Stop(fail("blocked_captcha", collected, "page"));
  if (settled && ready()) return;
  throw new Stop(fail(env.hasSession() ? "needs_template" : "needs_data_page", collected, need.join(",")));
}

async function readProducts(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, ["product_list"], collected);
  const template = env.template("product_list") as Template;
  const size = pageSizeOf(template, 24);
  const seen = new Set<string>();
  let total: number | undefined;
  for (let page = 1; page <= PRODUCT_MAX_PAGES; page += 1) {
    const request = buildReaderRequest(
      env.origin,
      "product_list",
      template,
      { query: { page_number: String(page), page_size: String(size) } },
      env.session(),
    );
    const response = await send(env, request, collected, { page });
    const found = findList(payloadOf(response.body), isProduct);
    if (!found) break;
    total = totalOf(response.body, found.parent) ?? total;
    const fresh = found.list.filter((item) => {
      const id = String(item.id ?? item.item_id ?? "");
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
    if (fresh.length === 0 || found.list.length < size) break;
    if (total !== undefined && seen.size >= total) break;
  }
  // The page's own campaign query is not replayed (its body lists the page's item ids): the
  // response the page itself got is attached when it has one.
  await env.waitFor(() => env.template("campaign_info")?.lastResponse !== undefined, 4_000);
  const campaign = env.template("campaign_info")?.lastResponse;
  if (campaign !== undefined) {
    collected.push({
      endpoint: "campaign_info",
      url: `${env.origin}${READER_ENDPOINTS.campaign_info.path}`,
      status: 200,
      body: campaign,
      capturedAt: env.now(),
      source: "page",
    });
  }
}

/** GMT+7 day bounds as the page's "yesterday" picker sends them (end = start + 86 399). */
export function dayBounds(day: string): { start_time: number; end_time: number } {
  const start = gmt7DateStart(day);
  return { start_time: start, end_time: start + 86_399 };
}

/** The homepage query's body when the page never made one: only keys the recon recorded. */
const ADS_HOMEPAGE_FALLBACK: Record<string, unknown> = { filter_list: [], use_paid_gmv: false };

/**
 * The ads list, one call set per finished GMT+7 day (the page's own homepage query with only the day
 * bounds and the page changed), plus the page's ROAS graph for that day. 0.3.19: after `days`, the
 * older `historyDays` of the once-per-shop history, newest first. A history day Shopee answers with an
 * error is kept (the scheduler records it as the earliest day Shopee allows) and ends the history
 * read; a history day is never started without room left in the job's budget.
 */
async function readAds(env: ReaderEnv, days: string[], collected: ReaderResponse[], historyDays: string[] = []): Promise<void> {
  await waitForPage(env, [], collected);
  // The page's own homepage query is the template; its graph query is optional. 0.3.20: the ads
  // page loads slowly (it timed out): the full template wait, twice what it had.
  await env.waitFor(() => env.template("ads_homepage") !== undefined, READER_TEMPLATE_WAIT_MS);
  await env.waitFor(() => env.template("ads_time_graph") !== undefined, 8_000);
  const home = env.template("ads_homepage");
  const graph = env.template("ads_time_graph");
  const homeBody = isRecord(home?.body) ? home.body : ADS_HOMEPAGE_FALLBACK;
  const limitNumber = Number(homeBody.limit);
  const limit = Number.isInteger(limitNumber) && limitNumber > 0 ? limitNumber : ADS_PAGE_LIMIT_DEFAULT;
  const usePaidGmv = homeBody.use_paid_gmv === true;
  /** One day's list pages (and graph). False when its first page was not data (history only). */
  const readDay = async (day: string | undefined, bounds: { start_time: number; end_time: number }, history: boolean): Promise<boolean> => {
    let rows = 0;
    for (let offset = 0; offset < ADS_MAX_ROWS_PER_DAY; offset += limit) {
      const request = buildReaderRequest(
        env.origin,
        "ads_homepage",
        home,
        { body: { ...bounds, offset, limit, use_paid_gmv: usePaidGmv } },
        env.session(),
        ADS_HOMEPAGE_FALLBACK,
      );
      const response = await send(env, request, collected, { ...(day ? { day } : {}), page: offset / limit + 1, usePaidGmv }, history);
      if (history && classify(response.status, response.body) !== "ok") return false;
      const found = findList(payloadOf(response.body), isAdsEntry);
      rows += found?.list.length ?? 0;
      if (!found || found.list.length < limit) break;
      const total = totalOf(response.body, found.parent);
      if (total !== undefined && rows >= total) break;
    }
    if (graph && day) {
      const request = buildReaderRequest(env.origin, "ads_time_graph", graph, { body: bounds }, env.session());
      await send(env, request, collected, { day }, history);
    }
    return true;
  };
  if (days.length === 0 && historyDays.length === 0) {
    // Connector 0.3.11: no day left to read, but the list's settings are refreshed once a day.
    // Read with yesterday's bounds and NO day tag, so no daily post is made from it.
    await readDay(undefined, dayBounds(gmt7Date(Math.floor(env.now() / 1000) - 86_400)), false);
    return;
  }
  for (const day of days) await readDay(day, dayBounds(day), false);
  for (const day of historyDays) {
    if (env.budget && env.budget.left < ADS_HISTORY_DAY_COST) return;
    if (!(await readDay(day, dayBounds(day), true))) return;
  }
}

/** The four read calls of a campaign edit page (Connector 0.3.11). */
export const ADS_DETAIL_ENDPOINTS: readonly ReaderEndpoint[] = [
  "ads_product_get",
  "ads_roi_recommend",
  "ads_budget_edit",
  "ads_expense_stats",
];

/**
 * One campaign edit page and the other ongoing campaigns' same answers. The page the scheduler
 * opened is `ids[0]`: its own answers are kept as the page loaded them. For every other id each
 * read call is replayed with only `campaign_id` changed (paced, one at a time). A call whose path
 * is not a read (isReadOnlyPasPath), or whose request has no `campaign_id`, is never replayed.
 */
async function readAdsDetail(env: ReaderEnv, ids: string[], collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, ["ads_product_get"], collected);
  for (const endpoint of ADS_DETAIL_ENDPOINTS.slice(1)) await env.waitFor(() => env.template(endpoint) !== undefined, 8_000);
  const opened = ids[0];
  for (const endpoint of ADS_DETAIL_ENDPOINTS) {
    const template = env.template(endpoint);
    const body = isRecord(template?.body) ? template.body : {};
    if (opened && template?.lastResponse !== undefined && String(body.campaign_id ?? "") === opened) {
      collected.push({
        endpoint,
        url: `${env.origin}${READER_ENDPOINTS[endpoint].path}`,
        status: 200,
        body: template.lastResponse,
        capturedAt: env.now(),
        source: "page",
        campaignId: opened,
      });
    }
  }
  for (const id of ids.slice(1)) {
    for (const endpoint of ADS_DETAIL_ENDPOINTS) {
      const template = env.template(endpoint);
      if (!isRecord(template?.body) || !("campaign_id" in template.body)) continue;
      if (!isReadOnlyPasPath(READER_ENDPOINTS[endpoint].path)) continue;
      const typed = typeof template.body.campaign_id === "number" ? Number(id) : id;
      const request = buildReaderRequest(env.origin, endpoint, template, { body: { campaign_id: typed } }, env.session());
      await send(env, request, collected, { campaignId: id }, true);
    }
  }
}

/**
 * The object holding a traffic answer's source blocks (`product_card`, `live`, ...), found by that
 * key a few levels deep whatever the envelope (`{code, result}` as recorded; 0.3.20 also
 * `{error, data}`, `{data}`, `{result}`). Null when there is none.
 */
export function trafficBlocks(body: unknown, depth = 3): Record<string, unknown> | null {
  const queue: { node: unknown; level: number }[] = [{ node: body, level: 0 }];
  while (queue.length > 0) {
    const { node, level } = queue.shift() as { node: unknown; level: number };
    if (!isRecord(node)) continue;
    if (isRecord(node.product_card)) return node;
    if (level < depth) for (const value of Object.values(node)) if (isRecord(value)) queue.push({ node: value, level: level + 1 });
  }
  return null;
}

/** Only the four source blocks of a traffic-details answer are kept (the funnel / pie data are not read). */
export function trimTrafficBody(body: unknown): unknown {
  if (!isRecord(body)) return body;
  const result = trafficBlocks(body);
  if (!result) return body;
  const kept: Record<string, unknown> = {};
  for (const key of ["product_card", "live", "video", "affiliate"]) {
    if (key in result) kept[key] = result[key];
  }
  return { code: body.code ?? body.error ?? 0, result: kept };
}

/** A finished GMT+7 day as the mydata `period=day` picker sends it (end = next midnight). */
export function trafficDayBounds(day: string): { start_time: number; end_time: number } {
  const start = gmt7DateStart(day);
  return { start_time: start, end_time: start + 86_400 };
}

/**
 * F4.4: the days one item_traffic job reads. A day is read whole or not at all (a day cut short is
 * read again from its first item, so its requests were wasted): days are taken, yesterday first,
 * while every item of the day still fits in `cap`; the first day is always taken (a shop with more
 * items than the cap still gets its first `cap` items for it).
 */
export function trafficDaysWithinCap(days: string[], itemCount: number, cap: number): string[] {
  if (itemCount <= 0) return [];
  const taken: string[] = [];
  let left = cap;
  for (const day of days) {
    if (taken.length > 0 && left < itemCount) break;
    taken.push(day);
    left -= itemCount;
  }
  return taken;
}

async function readItemTraffic(env: ReaderEnv, days: string[], itemIds: string[], collected: ReaderResponse[]): Promise<void> {
  // The re-confirmation modal means the page will never load its data: stop at once.
  const modal = () => env.passwordModalVisible?.() === true;
  const ready = await env.waitFor(() => modal() || env.hasSession(), READER_TEMPLATE_WAIT_MS);
  if (modal()) throw new Stop(fail("blocked_password_recheck", collected, "password_modal"));
  if (!ready) throw new Stop(fail("needs_data_page", collected, "traffic_details"));
  // The page's own details call (if it made one) is the template; else its other mydata headers.
  await env.waitFor(() => env.template("traffic_details") !== undefined, 8_000);
  const learned = env.template("traffic_details");
  const template: Template = {
    query: learned?.query ?? {},
    headers: learned?.headers ?? env.mydataHeaders?.(),
  };
  let requests = 0;
  let errorsInARow = 0;
  for (const day of trafficDaysWithinCap(days, itemIds.length, TRAFFIC_MAX_REQUESTS_PER_JOB)) {
    const bounds = trafficDayBounds(day);
    for (const itemId of itemIds) {
      if (requests >= TRAFFIC_MAX_REQUESTS_PER_JOB) return;
      requests += 1;
      const request = buildReaderRequest(
        env.origin,
        "traffic_details",
        template,
        {
          query: {
            start_time: String(bounds.start_time),
            end_time: String(bounds.end_time),
            period: "day",
            order_type: "confirmed",
            item_id: itemId,
          },
        },
        env.session(),
      );
      const response = await send(env, request, collected, { day, itemId }, true);
      response.body = trimTrafficBody(response.body);
      errorsInARow = classify(response.status, response.body) === "ok" ? 0 : errorsInARow + 1;
      if (errorsInARow >= TRAFFIC_MAX_CONSECUTIVE_ERRORS) {
        throw new Stop(fail("error", collected, `traffic_details:http_${response.status}`));
      }
    }
  }
}

/**
 * Shop traffic (0.3.19), in the scheduler's own Phân Tích Bán Hàng › Truy cập tab: for each day,
 * the same GET reads the backfill sends (the traffic overview on both order bases, and the shop
 * traffic dashboard by `period=day&dt=`), with the session and the mydata headers the page itself
 * used. A Seller Centre error code on one call is kept (the mapper skips it) and the job goes on;
 * a CAPTCHA, login wall or rate limit stops it like every reader.
 */
async function readTraffic(env: ReaderEnv, days: string[], collected: ReaderResponse[]): Promise<void> {
  const modal = () => env.passwordModalVisible?.() === true;
  const ready = await env.waitFor(() => modal() || env.hasSession(), READER_TEMPLATE_WAIT_MS);
  if (modal()) throw new Stop(fail("blocked_password_recheck", collected, "password_modal"));
  if (!ready) throw new Stop(fail("needs_data_page", collected, "traffic_overview"));
  const template: Template = { query: {}, headers: env.mydataHeaders?.() };
  for (const day of days) {
    for (const planned of buildBackfillDayPlan(day, env.now(), new Set(), false)) {
      if (planned.dataset !== "traffic_overview" && planned.dataset !== "shop_traffic" && planned.dataset !== "product_overview" && planned.dataset !== "promotion_daily" && planned.dataset !== "flash_sale") continue;
      const request = buildReaderRequest(env.origin, planned.dataset, template, { query: planned.params }, env.session());
      await send(env, request, collected, { day }, true);
    }
  }
}

async function readVouchers(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, ["voucher_list"], collected);
  const template = env.template("voucher_list") as Template;
  const limit = pageSizeOf(template, VOUCHER_PAGE_LIMIT_DEFAULT);
  const seen = new Set<string>();
  for (let offset = 0; offset < VOUCHER_MAX_ROWS; offset += limit) {
    const request = buildReaderRequest(
      env.origin,
      "voucher_list",
      template,
      { query: { offset: String(offset), limit: String(limit) } },
      env.session(),
    );
    const response = await send(env, request, collected, { page: offset / limit + 1 });
    const found = findList(payloadOf(response.body), isVoucher);
    if (!found) break;
    const fresh = found.list.filter((item) => {
      const id = String(item.voucher_id);
      if (seen.has(id)) return false;
      seen.add(id);
      return true;
    });
    const total = totalOf(response.body, found.parent);
    if (fresh.length === 0 || found.list.length < limit) break;
    if (total !== undefined && seen.size >= total) break;
  }
}

/**
 * 0.3.35 (batch-1124-a C4): the Combo tab's list (the page's own POST, replayed page by page with
 * only discount_type / offset / limit set), then each upcoming or running combo's detail (its
 * tiers, buyer limit and products; newest first, at most COMBO_DETAIL_MAX). Reads only.
 */
async function readCombos(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, ["combo_list"], collected);
  const template = env.template("combo_list") as Template;
  const learned = isRecord(template.body) && Number(template.body.limit) > 0 ? Number(template.body.limit) : COMBO_PAGE_LIMIT_DEFAULT;
  const limit = Math.min(Math.max(1, Math.floor(learned)), 50);
  const seen = new Map<string, number>();
  for (let offset = 0; offset < COMBO_MAX_ROWS; offset += limit) {
    const request = buildReaderRequest(
      env.origin,
      "combo_list",
      template,
      { body: { discount_type: COMBO_DISCOUNT_TYPE, time_status: 0, offset, limit } },
      env.session(),
    );
    const response = await send(env, request, collected, { page: offset / limit + 1 });
    const found = findList(payloadOf(response.body), isComboEntry);
    if (!found) break;
    let fresh = 0;
    for (const entry of found.list) {
      const deal = entry.bundle_deal as Record<string, unknown>;
      const id = String(deal.discount_id ?? "");
      if (!/^\d{1,20}$/.test(id) || seen.has(id)) continue;
      seen.set(id, Number(deal.time_status));
      fresh += 1;
    }
    if (fresh === 0 || found.list.length < limit) break;
  }
  const live = [...seen.entries()]
    .filter(([, status]) => COMBO_LIVE_STATUSES.has(status))
    .map(([id]) => id)
    .sort((a, b) => (BigInt(b) > BigInt(a) ? 1 : BigInt(b) < BigInt(a) ? -1 : 0))
    .slice(0, COMBO_DETAIL_MAX);
  // the detail is not called by the list page: the list's headers, the session, the combo's id only
  const detail: Template = { query: {}, headers: template.headers };
  for (const id of live) {
    const request = buildReaderRequest(env.origin, "combo_detail", detail, { query: { bundle_deal_id: id } }, env.session());
    await send(env, request, collected, {}, true);
  }
}

async function readHealth(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, [], collected);
  for (const endpoint of ["health_overview", "health_metric_list", "health_metric_configs"] as const) {
    const request = buildReaderRequest(env.origin, endpoint, env.template(endpoint), {}, env.session());
    await send(env, request, collected);
  }
}


// -- shop totals, order list, per-order income (Connector 0.3.11, P97 T1) ---------------------------

/** Range bounds of a finished-day range as a mydata picker sends them (end = last day's start + 86 399). */
function rangeBounds(first: string, last: string): { start_time: string; end_time: string } {
  return { start_time: String(gmt7DateStart(first)), end_time: String(gmt7DateStart(last) + 86_399) };
}

/**
 * Shop totals: the page's own key-metrics call is the template; it is replayed once for the whole
 * range (daily `points` come back for a range) and once for order-performance. Two requests.
 * TODO(first capture): the exact `period` value for a custom range (past7days / past30days are
 * what the page's picker offers; start_time / end_time carry the real bounds).
 */
async function readShopTotals(env: ReaderEnv, days: string[], collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, ["shop_key_metrics"], collected);
  const sorted = [...days].sort();
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  if (!first || !last) return;
  const period = { start: first, end: last };
  const label = sorted.length > 8 ? "past30days" : sorted.length > 1 ? "past7days" : "yesterday";
  const bounds = rangeBounds(first, last);
  const metrics = buildReaderRequest(
    env.origin,
    "shop_key_metrics",
    env.template("shop_key_metrics"),
    { query: { ...bounds, period: label } },
    env.session(),
  );
  await send(env, metrics, collected, { period });
  // The cancelled / returned split is on the same page; its own call is the template when seen.
  await env.waitFor(() => env.template("shop_order_performance") !== undefined, 8_000);
  const learned = env.template("shop_order_performance");
  const template: Template = { query: learned?.query ?? {}, headers: learned?.headers ?? env.mydataHeaders?.() };
  const performance = buildReaderRequest(
    env.origin,
    "shop_order_performance",
    template,
    { query: { ...bounds, period: label, order_type: "confirmed" } },
    env.session(),
  );
  await send(env, performance, collected, { period }, true);
}

/**
 * Product table of the last 30 finished days (recorded 2026-11-09): the page's own call is the
 * template; it is replayed for pages 1..PRODUCT_PERIOD_MAX_PAGES with only the range, the page and
 * the order kept as the recorded request sent them (confirmed sales descending). One answer holds
 * the placed, paid and confirmed values of every item, so placed needs no second read. Stops at
 * the page the answer's own `total` says is the last.
 */
async function readProductPeriod(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, ["product_performance"], collected);
  const days = lastFinishedDays(env.now(), PRODUCT_PERIOD_DAYS);
  const first = days[days.length - 1];
  const last = days[0];
  if (!first || !last) return;
  const period = { start: first, end: last };
  const bounds = rangeBounds(first, last);
  const template = env.template("product_performance") as Template;
  let seen = 0;
  for (let page = 1; page <= PRODUCT_PERIOD_MAX_PAGES; page += 1) {
    const request = buildReaderRequest(
      env.origin,
      "product_performance",
      template,
      {
        query: {
          ...bounds,
          period: "past30days",
          keyword: "",
          category_type: "shopee",
          category_id: "-1",
          page_size: String(PRODUCT_PERIOD_PAGE_SIZE),
          page_num: String(page),
          order_type: "confirmed",
          order_by: "confirmed_sales.desc",
        },
      },
      env.session(),
    );
    const response = await send(env, request, collected, { page, period });
    const result = payloadOf(response.body);
    const items = isRecord(result) && Array.isArray(result.items) ? result.items : [];
    seen += items.length;
    const total = totalOf(response.body, isRecord(result) ? result : undefined);
    if (items.length < PRODUCT_PERIOD_PAGE_SIZE || (total !== undefined && seen >= total)) break;
  }
}

/**
 * Group campaigns' per-product table (manual-mpd page, recorded 2026-11-09): the page's own answer
 * for the campaign it opened is kept as loaded; for each other group campaign the same call is
 * replayed with only `campaign_id` changed. Nothing is clicked (no Xóa, no Thêm sản phẩm).
 */
/** F4.5: at most this many (campaign x day) requests for past days in one ads_products job. */
export const ADS_PRODUCTS_MAX_DAY_REQUESTS = 60;

/**
 * F4.5: the page's own request body with its window set to one finished GMT+7 day (the unit of the
 * page's `start_time` / `end_time`, seconds or milliseconds, is kept). The end is the day's last second.
 */
export function adsProductsDayBody(body: Record<string, unknown>, day: string): Record<string, unknown> {
  const start = gmt7DateStart(day);
  const millis = typeof body.start_time === "number" && body.start_time > 1e12;
  const out: Record<string, unknown> = {
    start_time: millis ? start * 1000 : start,
    end_time: millis ? (start + 86_399) * 1000 : start + 86_399,
  };
  return out;
}

async function readAdsProducts(
  env: ReaderEnv,
  ids: string[],
  names: string[],
  collected: ReaderResponse[],
  days: string[] = [],
): Promise<void> {
  // Capture-only first: the page loads the table itself; a missing session must not discard it.
  const answered = () => env.template("ads_mpd_products")?.lastResponse !== undefined;
  if (!(await env.waitFor(() => env.hasSession() || answered(), READER_TEMPLATE_WAIT_MS)) && !answered()) {
    throw new Stop(fail("needs_data_page", collected, "ads_mpd_products"));
  }
  if (!(await env.waitFor(() => env.template("ads_mpd_products") !== undefined, READER_TEMPLATE_WAIT_MS))) {
    throw new Stop(fail("needs_template", collected, "ads_mpd_products"));
  }
  const template = env.template("ads_mpd_products") as Template;
  const body = isRecord(template.body) ? template.body : {};
  const opened = ids[0];
  // The page's own product/get answer names the campaign (recorded 2026-11-10): data.campaign.name.
  // Capture only (the page makes the call itself); the list title is the fallback.
  await env.waitFor(() => env.template("ads_product_get")?.lastResponse !== undefined, 4_000);
  const pageName = opened ? campaignNameFromGet(env.template("ads_product_get")?.lastResponse, opened) : undefined;
  const openedName = pageName ?? (names[0] ? names[0] : undefined);
  if (opened && template.lastResponse !== undefined && String(body.campaign_id ?? "") === opened) {
    collected.push({
      endpoint: "ads_mpd_products",
      url: `${env.origin}${READER_ENDPOINTS.ads_mpd_products.path}`,
      status: 200,
      body: template.lastResponse,
      capturedAt: env.now(),
      source: "page",
      campaignId: opened,
      ...(openedName ? { campaignName: openedName } : {}),
      ...bodyPeriod(body),
    });
  }
  if (!isReadOnlyPasPath(READER_ENDPOINTS.ads_mpd_products.path) || !("campaign_id" in body)) return;
  for (const [index, id] of ids.slice(1).entries()) {
    const typed = typeof body.campaign_id === "number" ? Number(id) : id;
    const request = buildReaderRequest(env.origin, "ads_mpd_products", template, { body: { campaign_id: typed } }, env.session());
    const name = names[index + 1];
    await send(env, request, collected, { campaignId: id, ...(name ? { campaignName: name } : {}), ...bodyPeriod(body) }, true);
  }
  // F4.5: past days, one request per campaign x day (the same GET-free POST the page makes, only the
  // window changed; a 1-day window is what fills the per-product daily spend). Never a click.
  let sent = 0;
  for (const day of days) {
    for (const [index, id] of ids.entries()) {
      if (sent >= ADS_PRODUCTS_MAX_DAY_REQUESTS) return;
      sent += 1;
      const typed = typeof body.campaign_id === "number" ? Number(id) : id;
      const window = adsProductsDayBody(body, day);
      const request = buildReaderRequest(
        env.origin,
        "ads_mpd_products",
        template,
        { body: { campaign_id: typed, ...window } },
        env.session(),
      );
      const name = (index === 0 ? openedName : undefined) ?? names[index];
      await send(env, request, collected, { campaignId: id, ...(name ? { campaignName: name } : {}), period: { start: day, end: day } }, true);
    }
  }
}

/**
 * The campaign name in a captured `product/get` answer (`data.campaign{campaign_id, name}`) when
 * it is the answer for `campaignId` (numeric or string id). Never a product name.
 */
export function campaignNameFromGet(answer: unknown, campaignId: string): string | undefined {
  const data = payloadOf(answer);
  const campaign = isRecord(data) && isRecord(data.campaign) ? data.campaign : undefined;
  if (!campaign || String(campaign.campaign_id ?? "") !== campaignId) return undefined;
  const name = campaign.name;
  return typeof name === "string" && name.trim() !== "" ? name.trim().slice(0, 255) : undefined;
}

/** The GMT+7 days a request body's `start_time` / `end_time` (unix seconds, top level or one level in) name. */
export function bodyPeriod(body: Record<string, unknown>): { period?: { start: string; end: string } } {
  const read = (node: Record<string, unknown>) => {
    const start = dayOf(node.start_time ?? node.start_date ?? node.from);
    const end = dayOf(node.end_time ?? node.end_date ?? node.to);
    return start && end ? { start, end } : undefined;
  };
  const direct = read(body);
  if (direct) return { period: direct };
  for (const value of Object.values(body)) {
    if (isRecord(value)) {
      const nested = read(value);
      if (nested) return { period: nested };
    }
  }
  return {};
}

/** Set the page number (or offset) wherever the page's request body keeps it; false when it has none. */
export function withListPage(body: unknown, page: number, size: number): unknown | null {
  let done = false;
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walk);
    if (!isRecord(node)) return node;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node)) {
      if (/^(page_number|page_no|page_num|pageNumber|page)$/.test(key) && typeof value === "number") {
        out[key] = page;
        done = true;
      } else if (/^(offset|from)$/.test(key) && typeof value === "number") {
        out[key] = (page - 1) * size;
        done = true;
      } else out[key] = walk(value);
    }
    return out;
  };
  const next = walk(body);
  return done ? next : null;
}

/** Replace the list of order ids in the cards request body; null when no list of those ids is found. */
export function withOrderIds(body: unknown, previous: readonly string[], next: readonly string[]): unknown | null {
  if (previous.length === 0) return null;
  const known = new Set(previous);
  let done = false;
  const idOf = (item: unknown): string | undefined => {
    if (typeof item === "number" || typeof item === "string") return String(item);
    if (isRecord(item)) return String(item.order_id ?? item.order_sn ?? "");
    return undefined;
  };
  const rebuild = (sample: unknown, id: string): unknown => {
    if (isRecord(sample)) return { ...sample, ...("order_id" in sample ? { order_id: Number.isNaN(Number(id)) ? id : Number(id) } : { order_sn: id }) };
    return typeof sample === "number" ? Number(id) : id;
  };
  const walk = (node: unknown): unknown => {
    if (Array.isArray(node)) {
      const ids = node.map(idOf);
      if (node.length > 0 && ids.every((id) => id !== undefined && known.has(id))) {
        done = true;
        return next.map((id) => rebuild(node[0], id));
      }
      return node.map(walk);
    }
    if (!isRecord(node)) return node;
    return Object.fromEntries(Object.entries(node).map(([key, value]) => [key, walk(value)]));
  };
  const out = walk(body);
  return done ? out : null;
}

/** `page_size` / `limit` wherever the page's request body keeps it. */
function bodyPageSize(body: unknown): number | undefined {
  if (!isRecord(body)) return undefined;
  for (const [key, value] of Object.entries(body)) {
    if (/^(page_size|pageSize|limit)$/.test(key) && typeof value === "number" && value > 0) return value;
    const nested = bodyPageSize(value);
    if (nested !== undefined) return nested;
  }
  return undefined;
}

function orderIdsOf(body: unknown): string[] {
  const found = findList(payloadOf(body), (o) => "order_id" in o || "order_sn" in o);
  return (found?.list ?? []).map((o) => String(o.order_id ?? o.order_sn));
}

/** The earliest `create_time` (unix seconds) of a card answer (raw or trimmed), or undefined. */
export function oldestOrderTime(cardsBody: unknown): number | undefined {
  // Through the trim: it flattens the card wrappers (order_card / order_info) to plain orders.
  const found = findList(payloadOf(trimOrderCards(cardsBody)), (o) => "order_id" in o || "order_sn" in o);
  let oldest: number | undefined;
  for (const order of found?.list ?? []) {
    const raw = Number(order.create_time);
    if (!Number.isFinite(raw) || raw <= 0) continue;
    const seconds = raw > 1e12 ? Math.floor(raw / 1000) : raw;
    oldest = oldest === undefined ? seconds : Math.min(oldest, seconds);
  }
  return oldest;
}

/** The GMT+7 day an order number names (its YYMMDD prefix), or undefined. */
export function orderSnDay(sn: string | undefined): string | undefined {
  const m = sn ? /^(\d{2})(\d{2})(\d{2})/.exec(sn) : null;
  if (!m) return undefined;
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (month < 1 || month > 12 || day < 1 || day > 31) return undefined;
  return `20${m[1]}-${m[2]}-${m[3]}`;
}

/** The orders an index answer names (trimmed: `order_id`, `order_sn`), as list links. */
export function orderLinksOfIndex(body: unknown): OrderLink[] {
  const found = findList(payloadOf(body), (o) => "order_id" in o || "order_sn" in o);
  const out: OrderLink[] = [];
  for (const o of found?.list ?? []) {
    const id = o.order_id !== undefined && o.order_id !== null ? String(o.order_id) : undefined;
    if (!id || !/^\d{1,20}$/.test(id)) continue;
    const sn = typeof o.order_sn === "string" && o.order_sn ? o.order_sn.toUpperCase() : undefined;
    out.push({ id, ...(sn ? { sn } : {}) });
  }
  return out;
}

/**
 * F4.10: pages 2..N of the order list, no click. The list page's own `order_search` request (its
 * body, headers) is replayed with only the page number changed, a pause before each page, until a
 * page is short (complete), a page's orders were all placed before `sinceDay` (complete), the page
 * cap (`partial:page_cap`), or the number of orders to read in detail reaches the per-run cap
 * (`partial:detail_cap`, said by the caller). Nothing replayable (no template, no page number in
 * its body) is `partial:first_page`: the job is not complete.
 */
async function readOrderIndexPages(
  env: ReaderEnv,
  collected: ReaderResponse[],
  orders: Map<string, OrderLink>,
  sinceDay: string,
): Promise<{ complete: boolean; note?: string }> {
  const search = env.template("order_search");
  if (!search || !isRecord(search.body) || !isReadOnlyOrderPath(READER_ENDPOINTS.order_search.path)) {
    return { complete: false, note: "partial:first_page" };
  }
  const size = bodyPageSize(search.body) ?? pageSizeOf(search, 40);
  if (withListPage(search.body, 2, size) === null) return { complete: false, note: "partial:first_page" };
  const random = env.random ?? Math.random;
  for (let page = 2; page <= ORDER_LIST_MAX_PAGES_PER_RUN; page += 1) {
    if (orders.size >= ORDER_DETAIL_MAX_PER_RUN) return { complete: true }; // the detail cap says the rest
    try {
      const body = withListPage(search.body, page, size) as Record<string, unknown>;
      await env.pause?.(ORDER_LIST_PAGE_GAP_MS + Math.floor(random() * ORDER_LIST_PAGE_GAP_JITTER_MS));
      const request = buildReaderRequest(env.origin, "order_search", search, { body }, env.session());
      const index = await send(env, request, collected, { page });
      index.body = trimOrderIndex(index.body);
      const links = orderLinksOfIndex(index.body);
      if (links.length === 0) return { complete: true };
      for (const link of links) if (!orders.has(link.id)) orders.set(link.id, link);
      if (links.length < size) return { complete: true };
      const days = links.map((link) => orderSnDay(link.sn));
      if (days.every((day) => day !== undefined && day < sinceDay)) return { complete: true };
    } catch (error) {
      // A failed replay keeps the pages already read; CAPTCHA / login / rate stops still stop everything.
      if (error instanceof Stop && error.outcome.status === "error") {
        return { complete: false, note: `partial:${error.outcome.detail ?? "error"}`.slice(0, 80) };
      }
      throw error;
    }
  }
  return { complete: false, note: "partial:page_cap" };
}

/**
 * The order list as the page shows it (0.3.20). Seller Centre's list page no longer calls the
 * list endpoints the hook could replay (it loads through Shopee's DRM bundle), so: the order ids
 * are read from the page's own order links on the page shown (0.3.28: the pager is never pressed);
 * then each order placed since `sinceDay` (by the order number's day) is read with GET
 * get_one_order (paced, counted against the budget) and trimmed in the page.
 * Returns a note: "no_new_orders" when none was placed since `sinceDay`, a "partial:..." note when
 * the read stopped early (more list pages left: "partial:first_page", the caps, the budget), else
 * undefined.
 */
async function readOrdersFromList(env: ReaderEnv, collected: ReaderResponse[], sinceDay?: string): Promise<string | undefined> {
  const orders = new Map<string, OrderLink>();
  let note: string | undefined;
  // 0.3.28 (F5.1b): the page the list was opened on only; its pager is never pressed. When orders
  // since sinceDay may sit on later pages, the note is "partial:first_page": the job is not complete,
  // so ordersCoveredDay stays and the next run reads from the same day again.
  const shown = env.orderLinks?.() ?? [];
  for (const link of shown) if (!orders.has(link.id)) orders.set(link.id, link);
  if (sinceDay !== undefined) {
    const days = shown.map((link) => orderSnDay(link.sn));
    const olderSeen = shown.length > 0 && days.every((day) => day !== undefined && day < sinceDay);
    if (!olderSeen && env.moreOrderPages?.()) {
      // F4.10: the pages after the one shown are read through the list's own index call, replayed
      // with only its page number changed (the page's captured request, never a click on the pager).
      // Only when the page made no such call (no template, no page number in it) is the job partial.
      const paged = await readOrderIndexPages(env, collected, orders, sinceDay);
      note = paged.complete ? undefined : paged.note;
    }
  }
  const wanted = [...orders.values()].filter((link) => {
    const day = orderSnDay(link.sn);
    return sinceDay === undefined || day === undefined || day >= sinceDay;
  });
  if (wanted.length === 0) return note ?? "no_new_orders";
  if (!isReadOnlyOrderDetailPath(READER_ENDPOINTS.order_detail.path)) return note;
  if (!(await env.waitFor(() => env.hasSession(), 10_000))) throw new Stop(fail("needs_data_page", collected, "order_detail"));
  // The page's own call to the order page (when the hook saw one) gives the headers; else the
  // headers of the list page's own order-service call (0.3.26); never invented ones.
  const template = env.template("order_detail") ?? orderServiceHeaders(env);
  for (const link of wanted.slice(0, ORDER_DETAIL_MAX_PER_RUN)) {
    if (env.budget && env.budget.left <= 0) return "partial:budget";
    const request = buildReaderRequest(env.origin, "order_detail", template, { query: { order_id: link.id } }, env.session());
    // One order that does not answer is skipped; CAPTCHA / login / rate still stop the job.
    const response = await send(env, request, collected, {}, true);
    response.body = trimOrderDetail(response.body);
  }
  if (wanted.length > ORDER_DETAIL_MAX_PER_RUN) return "partial:detail_cap";
  return note;
}

/**
 * Headers for a get_one_order read from the list page (0.3.26): the list page never calls it, so
 * the headers of the page's own order-service call (the cards / index request the hook saw) are
 * used; none when the page made no such call. Only the headers: never that call's query or body.
 */
function orderServiceHeaders(env: ReaderEnv): Template | undefined {
  for (const endpoint of ["order_cards", "order_search"] as const) {
    const headers = env.template(endpoint)?.headers;
    if (!headers) continue;
    const kept = Object.fromEntries(Object.entries(headers).filter(([name]) => name.toLowerCase() !== "content-type"));
    if (Object.keys(kept).length > 0) return { query: {}, headers: kept };
  }
  return undefined;
}

/** The page's own card answer holds at least one order (not only that the hook kept an answer). */
export function cardsHoldOrders(lastResponse: unknown): boolean {
  if (lastResponse === undefined) return false;
  const trimmed = trimOrderCards(lastResponse) as { data?: { list?: unknown[] } };
  return (trimmed.data?.list?.length ?? 0) > 0;
}

/**
 * The order list: through the old list endpoints when the page's own card answer holds orders;
 * else through the page's own order links (0.3.20, readOrdersFromList). 0.3.26: a card answer the
 * hook kept but that holds no order (Shopee's DRM bundle) no longer wins over the links: before,
 * that answer mapped to 0 orders, silently ("orders:0_rows:ignored", 15-17/11). A page that shows
 * its "no orders" state ends the job as "no_orders"; a card answer without orders on a page that
 * shows no order link ends it as "no_ids_from_page".
 */
async function readOrders(env: ReaderEnv, collected: ReaderResponse[], sinceDay?: string): Promise<string | undefined> {
  const answered = () => cardsHoldOrders(env.template("order_cards")?.lastResponse);
  if (env.orderLinks) {
    const shown = () => (env.orderLinks?.().length ?? 0) > 0;
    const empty = () => env.orderListEmpty?.() === true;
    await env.waitFor(() => answered() || shown() || empty(), READER_TEMPLATE_WAIT_MS);
    // An empty state can flash while the list loads: give the cards a moment more.
    if (!answered() && !shown() && empty()) await env.waitFor(() => answered() || shown(), 5_000);
    if (!answered()) {
      if (shown()) return readOrdersFromList(env, collected, sinceDay);
      if (empty()) return "no_orders";
      if (env.template("order_cards")?.lastResponse !== undefined) return "no_ids_from_page";
      throw new Stop(fail(env.hasSession() ? "needs_template" : "needs_data_page", collected, "order_list"));
    }
  }
  const note = await readOrdersFromApi(env, collected, sinceDay);
  const bundles = await readBundleDetails(env, collected);
  return note ?? bundles;
}

/** a2 C-A2: a get_one_order read for a combo's order was refused (or gave no order): its lines stay as the card had them. */
export const BUNDLE_DETAIL_REFUSED = "bundle_detail_refused";

/**
 * batch-1123-a2 C-A2: on the card-list path, the orders whose card has a line naming no SKU (a
 * combo's parent row) are read one by one with get_one_order (budget-counted, paced, trimmed in
 * the page, the same request as the links path), so their lines carry the item ids. A refused read
 * leaves the card's lines and says so in the note.
 */
async function readBundleDetails(env: ReaderEnv, collected: ReaderResponse[]): Promise<string | undefined> {
  const ids = cardOrdersWithoutSku(collected);
  if (ids.length === 0 || !isReadOnlyOrderDetailPath(READER_ENDPOINTS.order_detail.path)) return undefined;
  const template = env.template("order_detail") ?? orderServiceHeaders(env);
  let refused = false;
  for (const id of ids.slice(0, ORDER_DETAIL_MAX_PER_RUN)) {
    if (env.budget && env.budget.left <= 0) return "partial:budget";
    const request = buildReaderRequest(env.origin, "order_detail", template, { query: { order_id: id } }, env.session());
    const response = await send(env, request, collected, {}, true);
    response.body = trimOrderDetail(response.body);
    if (classify(response.status, response.body) !== "ok" || !isRecord(payloadOf(response.body))) refused = true;
  }
  return refused ? BUNDLE_DETAIL_REFUSED : undefined;
}

/**
 * The order list through the list endpoints (0.3.11-0.3.19; kept for a Seller Centre that calls
 * them again): the page's OWN first answers are kept (trimmed in the page); pages 2..N are
 * replayed from the page's request templates, a pause of 20-45 s before each. 0.3.19 catches up by
 * date: it stops once a page's oldest order was placed before `sinceDay` (never before
 * ORDER_LIST_MIN_PAGES pages, the 0.3.18 depth), on a short page, or at ORDER_LIST_MAX_PAGES_PER_RUN
 * ("partial:page_cap": the next run reads further back). Nothing is replayed when the page's
 * request has no recognisable page number or id list (then only what the page loaded is read).
 */
async function readOrdersFromApi(env: ReaderEnv, collected: ReaderResponse[], sinceDay?: string): Promise<string | undefined> {
  const cutoff = sinceDay ? gmt7DateStart(sinceDay) : undefined;
  const reachedSince = (page: number, cardsBody: unknown): boolean => {
    if (cutoff === undefined) return false;
    if (page < ORDER_LIST_MIN_PAGES) return false;
    const oldest = oldestOrderTime(cardsBody);
    return oldest !== undefined && oldest < cutoff;
  };
  const answered = () => env.template("order_cards")?.lastResponse !== undefined;
  if (!(await env.waitFor(() => env.hasSession() || answered(), READER_TEMPLATE_WAIT_MS)) && !answered()) {
    throw new Stop(fail("needs_data_page", collected, "order_cards"));
  }
  await env.waitFor(() => answered() && env.template("order_search")?.lastResponse !== undefined, READER_TEMPLATE_WAIT_MS);
  const search = env.template("order_search");
  const cards = env.template("order_cards");
  if (cards?.lastResponse === undefined) throw new Stop(fail("needs_template", collected, "order_cards"));
  for (const [endpoint, template] of [["order_search", search], ["order_cards", cards]] as const) {
    if (template?.lastResponse !== undefined) {
      collected.push({
        endpoint,
        url: `${env.origin}${READER_ENDPOINTS[endpoint].path}`,
        status: 200,
        body: trimCaptured(endpoint, template.lastResponse),
        capturedAt: env.now(),
        source: "page",
        page: 1,
      });
    }
  }
  if (!search || !isRecord(search.body) || !isRecord(cards.body)) return undefined;
  if (!isReadOnlyOrderPath(READER_ENDPOINTS.order_search.path) || !isReadOnlyOrderPath(READER_ENDPOINTS.order_cards.path)) return undefined;
  const size = bodyPageSize(search.body) ?? pageSizeOf(search, 40);
  // The cards template still holds the FIRST page's ids: every later page swaps those out.
  const firstIds = orderIdsOf(search.lastResponse);
  const random = env.random ?? Math.random;
  if (reachedSince(1, cards.lastResponse)) return undefined;
  for (let page = 2; page <= ORDER_LIST_MAX_PAGES_PER_RUN; page += 1) {
    try {
      const indexBody = withListPage(search.body, page, size);
      if (indexBody === null || firstIds.length === 0) return undefined;
      await env.pause?.(ORDER_LIST_PAGE_GAP_MS + Math.floor(random() * ORDER_LIST_PAGE_GAP_JITTER_MS));
      const indexRequest = buildReaderRequest(env.origin, "order_search", search, { body: indexBody as Record<string, unknown> }, env.session());
      const index = await send(env, indexRequest, collected, { page });
      index.body = trimOrderIndex(index.body);
      const ids = orderIdsOf(index.body);
      if (ids.length === 0) return undefined;
      const cardBody = withOrderIds(cards.body, firstIds, ids);
      if (cardBody === null) return undefined;
      const cardRequest = buildReaderRequest(env.origin, "order_cards", cards, { body: cardBody as Record<string, unknown> }, env.session());
      const answer = await send(env, cardRequest, collected, { page });
      answer.body = trimOrderCards(answer.body);
      if (ids.length < size) return undefined;
      if (reachedSince(page, answer.body)) return undefined;
    } catch (error) {
      // A failed replay of page >= 2 keeps what was already read: the page's own answers and the
      // complete pages before it are posted; CAPTCHA / login / rate stops still stop everything.
      if (error instanceof Stop && error.outcome.status === "error") {
        for (let i = collected.length - 1; i >= 0; i -= 1) if ((collected[i]!.page ?? 1) >= page) collected.splice(i, 1);
        return `partial:${error.outcome.detail ?? "error"}`.slice(0, 80);
      }
      throw error;
    }
  }
  // Pages left to read: a by-date job says so (the scheduler then reads further back next time).
  return cutoff === undefined ? undefined : "partial:page_cap";
}

/** Query / body key of the page's own income call whose value is the order it opened. */
function orderKeyIn(template: Template, orderId: string): { where: "query" | "body"; key: string } | null {
  for (const [key, value] of Object.entries(template.query)) if (value === orderId) return { where: "query", key };
  if (isRecord(template.body)) {
    for (const [key, value] of Object.entries(template.body)) if (String(value) === orderId) return { where: "body", key };
  }
  return null;
}

/**
 * The order page as shown (0.3.32): for the order it opened (`ids[0]`, one order per page), its
 * "Doanh thu" rows become one income answer (the same `{name, amount}` items the income mapper
 * reads) when the order is completed (`incomeFor`), and its product lines put their "SKU phân
 * loại" on the order's stored answer when a line named none (`fixBodies`): an order_detail answer
 * the order-line mapper reads again. The other ids (none: the scheduler opens one page per order)
 * are left for their own page.
 */
function readOrderPage(
  env: ReaderEnv,
  ids: string[],
  collected: ReaderResponse[],
  sns: string[],
  job: Pick<ReaderJob, "incomeFor" | "fixBodies" | "fixLast">,
): string | undefined {
  const opened = ids[0];
  if (!opened) return undefined;
  const sn = sns[0] ? { orderSn: sns[0] } : {};
  const at = env.now();
  const income = env.orderPageIncome?.() ?? [];
  const buyer = env.orderPageBuyer?.() ?? [];
  const wantIncome = job.incomeFor?.[0] !== false;
  // a2 C-A10: only a page that shows the final amount is posted as the order's income
  const incomeNote = wantIncome && !pageIncomeFinal(income) ? incomeMissNote(income) : undefined;
  if (wantIncome && pageIncomeFinal(income)) {
    collected.push({ endpoint: "order_income_components", url: `${env.origin}${READER_PAGES.order_income.path}${opened}`, status: 200, body: { code: 0, data: { items: income, ...(buyer.length > 0 ? { buyer_items: buyer } : {}) } }, capturedAt: at, source: "page", orderId: opened, ...sn });
  }
  const stored = job.fixBodies?.[0];
  let note: string | undefined;
  if (stored) {
    const matched = withPageSkus(stored, env.orderPageItems?.() ?? []);
    // 0.3.32: the last allowed read (PAGE_FIX_MAX_FAILS) that still cannot match posts the lines as
    // "unresolved_item": the order is not read again for them (Juli keeps the day as a hole)
    const fixed = matched ?? (job.fixLast?.[0] ? withUnresolvedSkus(stored) : null);
    if (fixed) collected.push({ endpoint: "order_detail", url: `${env.origin}${READER_PAGES.order_income.path}${opened}`, status: 200, body: fixed, capturedAt: at, source: "page", orderId: opened, ...sn });
    note = matched ? undefined : fixed ? "unresolved_item" : linesMissNote(env.orderPageItems?.() ?? [], stored);
  }
  return ids.length > 1 ? "partial:one_order_per_page" : (note ?? incomeNote);
}

/** a2 C-A10: the order page showed its income rows but not "Doanh Thu Đơn Hàng" within the wait: nothing posted for it. */
export const INCOME_NOT_SHOWN = "income_final_not_shown";
/** The order page's lines could not be matched to the order's answer lines: nothing posted for them. */
export const PAGE_LINES_UNMATCHED = "page_lines_unmatched";

/** Outcome-safe text: no separators the outcome uses ("|", ",", "=", ":"). */
const noteSafe = (t: string) => t.replace(/[|,=:/]/g, " ").replace(/\s+/g, " ").trim();

/**
 * 0.3.34 (C-H4): "income_final_not_shown:<rows>:<label 1>/<label 2>/<label 3>": how many income rows
 * the page showed and its first three labels (plain, cut), never an amount.
 */
export function incomeMissNote(income: readonly { name: string }[]): string {
  const labels = income.slice(0, 3).map((i) => noteSafe(plainLabel(i.name)).slice(0, 24));
  return `${INCOME_NOT_SHOWN}:${income.length}${labels.length > 0 ? `:${labels.join("/")}` : ""}`;
}

/** The order answer's lines: top-level lines and their combo sub-lines (`sub_items`). */
function answerLineCounts(body: unknown): { lines: number; subs: number } {
  const order = isRecord(body) ? payloadOf(body) : undefined;
  const items = isRecord(order) && Array.isArray(order.items) ? order.items.filter(isRecord) : [];
  const subs = items.reduce((n, item) => n + (Array.isArray(item.sub_items) ? item.sub_items.length : 0), 0);
  return { lines: items.length, subs };
}

/**
 * 0.3.34 (C-H5): "page_lines_unmatched:page_<n>:answer_<lines>[+<sub-lines>]": the page's product
 * lines against the order answer's lines (a combo's parent and its children), counts only.
 */
export function linesMissNote(page: readonly PageItem[], stored: unknown): string {
  const { lines, subs } = answerLineCounts(stored);
  return `${PAGE_LINES_UNMATCHED}:page_${page.length}:answer_${lines}${subs > 0 ? `+${subs}` : ""}`;
}
/** How long the reader waits for the order page's "Doanh Thu Đơn Hàng" row once the page shows its lines. */
export const PAGE_INCOME_WAIT_MS = 15_000;

/**
 * Per-order income: the order page the scheduler opened is `ids[0]`: its own answer is kept; for
 * every other id the same GET is replayed with only the order id changed (one request each, at the
 * normal pace). A call whose template shows no order id is never replayed.
 */
async function readOrderIncome(
  env: ReaderEnv,
  ids: string[],
  collected: ReaderResponse[],
  sns: string[] = [],
  job: Pick<ReaderJob, "incomeFor" | "fixBodies" | "fixLast"> = {},
): Promise<string | undefined> {
  const snOf = (index: number) => (sns[index] ? { orderSn: sns[index] } : {});
  // 0.3.26: an account without the Tài chính right sees a permission page (the income call is
  // never made) or the page's own income call is refused: "blocked_no_permission", never silent.
  const denied = () => env.permissionDeniedVisible?.() === true;
  const own = () => env.template("order_income_components");
  const refused = () => {
    const t = own();
    return t !== undefined && t.lastResponse === undefined && t.lastStatus === 403 && Number(t.lastCode) !== ANTI_FRAUD_CODE;
  };
  const walled = () => env.captchaVisible?.() === true || env.passwordModalVisible?.() === true;
  // 0.3.32 (C1 + C3): the order page's own call loads before the hook sees it, so the page is READ:
  // its "Doanh thu" rows and its product lines, for the one order this page shows.
  const shown = () => (env.orderPageIncome?.().length ?? 0) > 0 || (env.orderPageItems?.().length ?? 0) > 0;
  const called = () => env.hasSession() && env.template("order_income_components") !== undefined;
  const settled = await env.waitFor(() => denied() || walled() || shown() || called(), READER_TEMPLATE_WAIT_MS);
  if (settled && denied()) throw new Stop(fail("blocked_no_permission", collected, "page"));
  if (env.passwordModalVisible?.()) throw new Stop(fail("blocked_password_recheck", collected, "password_modal"));
  if (env.captchaVisible?.()) throw new Stop(fail("blocked_captcha", collected, "page"));
  if (shown() && !called()) {
    // a2 C-A10: the lines can draw before the "Doanh thu" block: wait for its final amount.
    // 0.3.34 (C-H5): and the block before the lines: an order read for its lines also waits until
    // the page's product lines match its answer (same wait), so a half-drawn page is not "unmatched".
    const incomeReady = () => job.incomeFor?.[0] === false || pageIncomeFinal(env.orderPageIncome?.() ?? []);
    const stored = job.fixBodies?.[0];
    const linesReady = () => !stored || withPageSkus(stored, env.orderPageItems?.() ?? []) !== null;
    if (!(incomeReady() && linesReady())) await env.waitFor(() => incomeReady() && linesReady(), PAGE_INCOME_WAIT_MS);
    return readOrderPage(env, ids, collected, sns, job);
  }
  // 0.3.31 waited for the page's detail call too, but the order page makes it before the hook is
  // in place (capture 2026-11-23), so a page whose income call WAS seen ended needs_template
  // (0.3.32): the income call is all the replay needs.
  await waitForPage(env, ["order_income_components"], collected);
  if (refused()) throw new Stop(fail("blocked_no_permission", collected, `http_403${own()?.lastCode ? `_code_${own()?.lastCode}` : ""}`));
  const template = env.template("order_income_components") as Template;
  if (template.lastResponse !== undefined && isPermissionRefusal(200, template.lastResponse)) {
    throw new Stop(fail("blocked_no_permission", collected, `http_200_code_${answerCode(template.lastResponse)}`));
  }
  const opened = ids[0];
  if (opened && template.lastResponse !== undefined) {
    collected.push({
      endpoint: "order_income_components",
      url: `${env.origin}${READER_ENDPOINTS.order_income_components.path}`,
      status: 200,
      body: template.lastResponse,
      capturedAt: env.now(),
      source: "page",
      orderId: opened,
      ...snOf(0),
    });
  }
  const where = opened ? orderKeyIn(template, opened) : null;
  // a2 C-A10: an order whose answer has no final amount yet is skipped and said (`income_not_final`)
  const notFinal = () => (incomeNotFinal(collected) ? INCOME_NOT_FINAL : undefined);
  // 0.3.26: no order key in the page's own call: the other orders cannot be requested. Said, not
  // silent ("no_order_key" when not one order was read; else the rest is left for the next run).
  if (!where) {
    if (ids.length <= 1) return notFinal();
    return collected.some((r) => r.endpoint === "order_income_components") ? "partial:no_order_key" : "no_order_key";
  }
  for (const [offset, id] of ids.slice(1).entries()) {
    const overrides = where.where === "query" ? { query: { [where.key]: id } } : { body: { [where.key]: id } };
    const request = buildReaderRequest(env.origin, "order_income_components", template, overrides, env.session());
    // An income answer that is not data (a refused order) is skipped; a rate stop still stops all.
    await send(env, request, collected, { orderId: id, ...snOf(offset + 1) }, true, true);
  }
  return notFinal();
}

/** a2 C-A10: an income answer without its final amount (the order is not final yet): that order was skipped. */
export const INCOME_NOT_FINAL = "income_not_final";

// -- affiliate ("Tăng Đơn Cùng KOL") ---------------------------------------------------------
//
// HARD RULE: no `*Mutation` is ever sent or replayed, and nothing is clicked. The conversion
// report is the only affiliate endpoint replayed (a GET, with only its page number and purchase
// window changed); every other affiliate answer is the one the page loaded itself.

/** Order fields of a conversion-report answer a mapper may read. Buyer data and the creator's
 *  display name / avatar / platform user id never leave the page. */
const CONVERSION_ORDER_KEYS = [
  "order_id",
  "purchase_time",
  "conversion_complete_time",
  "order_complete_time",
  "order_status",
  "fraud_status",
  "shopee_username",
  "linked_mcn_name",
  "traffic_type",
  // The channel Seller Centre shows ("Kênh"): a Shopee surface (internal_source, e.g. Shopeevideo)
  // or the outside one (last_external_source, e.g. Facebook / Zalo / Code Sharing). Labels only.
  "internal_source",
  "last_external_source",
  "items",
] as const;
const CONVERSION_ITEM_KEYS = [
  "item_id",
  "model_id",
  "item_price",
  "dis_item_price",
  "actual_amount",
  "dis_actual_amount",
  "refunded_amount",
  "dis_refunded_amount",
  "qty",
  "expense",
  "campaign_type",
  "fraud_status",
  "ams_deduction_status",
  "ams_deduction_method",
  "ams_deduction_time",
  "brand_commission_rate",
] as const;
/** Per-KOL fields kept from `affiliate_performance` (no avatar, no platform user id). */
const PERFORMANCE_KEYS = [
  "affiliate_id",
  "shopee_username",
  "clicks",
  "orders",
  "gmv",
  "dis_gmv",
  "est_commission",
  "dis_est_commission",
  "actual_commission",
  "conversion_rate",
  "roi",
  "item_sold",
  "total_buyers",
  "new_buyers",
] as const;

function pick(source: Record<string, unknown>, keys: readonly string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of keys) if (key in source) out[key] = source[key];
  return out;
}

function mapList(body: unknown, rowKeys: readonly string[], nested?: { key: string; keys: readonly string[] }): unknown {
  if (!isRecord(body)) return body;
  const data = isRecord(body.data) ? body.data : null;
  if (!data || !Array.isArray(data.list)) return body;
  const list = data.list.filter(isRecord).map((row) => {
    const kept = pick(row, rowKeys);
    if (nested && Array.isArray(row[nested.key])) {
      kept[nested.key] = (row[nested.key] as unknown[]).filter(isRecord).map((r) => pick(r, nested.keys));
    }
    return kept;
  });
  return { code: body.code, msg: body.msg, data: { ...data, list } };
}

/** A conversion-report answer with only the fields the mapper reads. */
export function trimConversionBody(body: unknown): unknown {
  return mapList(body, CONVERSION_ORDER_KEYS, { key: "items", keys: CONVERSION_ITEM_KEYS });
}

/** What a captured answer may keep before it leaves the page (personal fields dropped). */
export function trimCaptured(endpoint: ReaderEndpoint, body: unknown): unknown {
  if (endpoint === "affiliate_performance") return mapList(body, PERFORMANCE_KEYS);
  if (endpoint === "affiliate_conversion") return trimConversionBody(body);
  // Order list: buyer name, address and phone are dropped IN THE PAGE (allowlist).
  if (endpoint === "order_search") return trimOrderIndex(body);
  if (endpoint === "order_cards") return trimOrderCards(body);
  return body;
}

export const isConversionOrder = (o: Record<string, unknown>) => "order_id" in o && Array.isArray(o.items);

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

/** A unix-seconds (or ms) value or a YYYY-MM-DD / DD-MM-YYYY string as a GMT+7 day. */
function dayOf(value: unknown): string | undefined {
  const n = typeof value === "string" && /^\d{9,13}$/.test(value) ? Number(value) : value;
  if (typeof n === "number" && Number.isFinite(n) && n > 1e9) {
    const seconds = n > 1e12 ? Math.floor(n / 1000) : n;
    return new Date((seconds + 7 * 3600) * 1000).toISOString().slice(0, 10);
  }
  if (typeof value === "string") {
    if (DAY_RE.test(value)) return value;
    const vn = /^(\d{2})-(\d{2})-(\d{4})$/.exec(value);
    if (vn) return `${vn[3]}-${vn[2]}-${vn[1]}`;
    if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  }
  return undefined;
}

/** [key, value] of every non-object leaf, descending into nested records (not lists) to `depth`. */
function leafEntries(node: Record<string, unknown>, depth: number): [string, unknown][] {
  const out: [string, unknown][] = [];
  for (const [key, value] of Object.entries(node)) {
    if (isRecord(value)) {
      if (depth > 0) out.push(...leafEntries(value, depth - 1));
    } else {
      out.push([key, value]);
    }
  }
  return out;
}

/**
 * The days a page asked for, read from its own request: query params or GraphQL variables whose
 * name says start / end (startTime, start_time, purchase_time_s, ...). Undefined when none.
 */
export function periodOfTemplate(template: Template | undefined): { start: string; end: string } | undefined {
  if (!template) return undefined;
  const fields: [string, unknown][] = Object.entries(template.query);
  const body = isRecord(template.body) ? template.body : undefined;
  const variables = body && isRecord(body.variables) ? body.variables : body;
  // GraphQL variables nest the range (`input.timeRange.startTime`): read the leaves, 4 levels deep.
  if (variables) fields.push(...leafEntries(variables, 4));
  let start: string | undefined;
  let end: string | undefined;
  for (const [key, value] of fields) {
    const day = dayOf(value);
    if (!day) continue;
    if (/(start|begin|from|_s$)/i.test(key)) start = start ?? day;
    else if (/(end|to$|_e$)/i.test(key)) end = end ?? day;
  }
  if (start && end) return start <= end ? { start, end } : { start: end, end: start };
  if (start || end) return { start: (start ?? end) as string, end: (end ?? start) as string };
  return undefined;
}

/** The purchase windows the conversion report is read for: the last finished 30 days, then any
 *  history windows the job carries (each ≤ 31 days, Juli's period cap), newest first. */
export function conversionWindows(nowMs: number, history: readonly ConversionWindow[] = []): ConversionWindow[] {
  const days = lastFinishedDays(nowMs, AFFILIATE_WINDOW_DAYS);
  if (days.length === 0) return [...history];
  const sorted = [...days].sort();
  return [{ start: sorted[0] as string, end: sorted[sorted.length - 1] as string }, ...history];
}

async function readAffiliateConversions(
  env: ReaderEnv,
  collected: ReaderResponse[],
  history: readonly ConversionWindow[] = [],
): Promise<void> {
  // The conversion page's own call is the template. It often carries no SPC_CDS query,
  // so waiting on the session first ended the job as needs_data_page with nothing posted.
  const seen = () => env.template("affiliate_conversion") !== undefined;
  if (!(await env.waitFor(() => env.hasSession() || seen(), READER_TEMPLATE_WAIT_MS))) {
    throw new Stop(fail("needs_data_page", collected, "affiliate_conversion"));
  }
  await env.waitFor(seen, READER_TEMPLATE_WAIT_MS / 2);
  const template = env.template("affiliate_conversion");
  const size = template ? pageSizeOf(template, AFFILIATE_PAGE_SIZE_DEFAULT) : AFFILIATE_PAGE_SIZE_DEFAULT;
  for (const period of conversionWindows(env.now(), history)) {
    await readConversionWindow(env, collected, template, size, period);
  }
}

async function readConversionWindow(
  env: ReaderEnv,
  collected: ReaderResponse[],
  template: ReturnType<ReaderEnv["template"]>,
  size: number,
  period: ConversionWindow,
): Promise<void> {
  const window = {
    purchase_time_s: String(gmt7DateStart(period.start)),
    purchase_time_e: String(gmt7DateStart(period.end) + 86_399),
  };
  let rows = 0;
  for (let page = 1; rows < AFFILIATE_MAX_ROWS; page += 1) {
    const request = buildReaderRequest(
      env.origin,
      "affiliate_conversion",
      template,
      { query: { page_num: String(page), page_size: String(size), ...window } },
      env.session(),
    );
    const response = await send(env, request, collected, { page, period });
    response.body = trimConversionBody(response.body);
    const found = findList(payloadOf(response.body), isConversionOrder);
    const count = found?.list.length ?? 0;
    rows += count;
    if (!found || count < size) break;
    const total = totalOf(response.body, found.parent);
    if (total !== undefined && rows >= total) break;
  }
}

/** The answers the affiliate page loaded itself, for `endpoints` (none replayed). */
async function readAffiliateCaptured(
  env: ReaderEnv,
  endpoints: readonly ReaderEndpoint[],
  collected: ReaderResponse[],
): Promise<void> {
  // Capture-only: the page's own answer is enough. A missing SPC_CDS must not discard it.
  const answered = () => endpoints.some((endpoint) => env.template(endpoint)?.lastResponse !== undefined);
  if (!(await env.waitFor(() => env.hasSession() || answered(), READER_TEMPLATE_WAIT_MS)) && !answered()) {
    throw new Stop(fail("needs_data_page", collected, endpoints.join(",")));
  }
  const every = () => endpoints.every((endpoint) => env.template(endpoint)?.lastResponse !== undefined);
  await env.waitFor(every, READER_TEMPLATE_WAIT_MS);
  await env.waitFor(() => env.template("affiliate_latest_date")?.lastResponse !== undefined, 2_000);
  const latest = env.template("affiliate_latest_date")?.lastResponse;
  const latestDay = latestReportDay(latest);
  let any = false;
  for (const endpoint of endpoints) {
    const template = env.template(endpoint);
    if (template?.lastResponse === undefined) continue;
    any = true;
    const period = periodOfTemplate(template) ?? (latestDay ? { start: latestDay, end: latestDay } : undefined);
    collected.push({
      endpoint,
      url: `${env.origin}${READER_ENDPOINTS[endpoint].path}`,
      status: 200,
      body: trimCaptured(endpoint, template.lastResponse),
      capturedAt: env.now(),
      source: "page",
      ...(period ? { period } : {}),
    });
  }
  if (!any && endpoints.includes("affiliate_content_summary") && env.contentEmptyVisible?.()) {
    // 0.3.32: Phân tích Nội dung shows "0 Nội dung" / "Không có dữ liệu" for its newest day: an empty day
    const day = latestDay ?? gmt7Date(Math.floor(env.now() / 1000) - 86_400);
    collected.push({
      endpoint: "affiliate_content_summary",
      url: `${env.origin}${READER_PAGES.affiliate_content.path}`,
      status: 200,
      body: { code: 0, data: {} },
      capturedAt: env.now(),
      source: "page",
      period: { start: day, end: day },
    });
    return;
  }
  if (!any) throw new Stop(fail("needs_template", collected, endpoints.join(",")));
}

/** The newest day the affiliate service has data for (`latest_report_date`), any shape. */
export function latestReportDay(body: unknown): string | undefined {
  const queue: unknown[] = [payloadOf(body), body];
  while (queue.length > 0) {
    const node = queue.shift();
    const direct = dayOf(node);
    if (direct) return direct;
    if (isRecord(node)) for (const value of Object.values(node)) queue.push(value);
  }
  return undefined;
}

/** The captured endpoints each affiliate page reader keeps. */
export const AFFILIATE_CAPTURES: Partial<Record<ReaderId, readonly ReaderEndpoint[]>> = {
  affiliate_kols: ["affiliate_performance"],
  affiliate_dashboard: ["affiliate_seller_daily"],
  affiliate_products: ["affiliate_item_detail"],
  affiliate_campaigns: ["affiliate_shop_campaign"],
  affiliate_commissions: ["affiliate_commission_list"],
  affiliate_content: ["affiliate_content_summary"],
  affiliate_bills: ["affiliate_validation"],
};

/** Run one reader job against the open Seller Centre page. Never throws. */
export async function runReaderJob(job: ReaderJob, env: ReaderEnv): Promise<ReaderOutcome> {
  const collected: ReaderResponse[] = [];
  let partial: string | undefined;
  try {
    switch (job.id) {
      case "products":
        await readProducts(env, collected);
        break;
      case "item_traffic":
        await readItemTraffic(env, job.days ?? [], job.itemIds ?? [], collected);
        break;
      case "ads":
        await readAds(env, job.days ?? [], collected, job.historyDays ?? []);
        break;
      case "ads_detail":
        await readAdsDetail(env, job.campaignIds ?? [], collected);
        break;
      case "vouchers":
        await readVouchers(env, collected);
        break;
      case "combos":
        await readCombos(env, collected);
        break;
      case "product_period":
        await readProductPeriod(env, collected);
        break;
      case "ads_products":
        await readAdsProducts(env, job.campaignIds ?? [], job.campaignNames ?? [], collected, job.days ?? []);
        break;
      case "shop_totals":
        await readShopTotals(env, job.days ?? [], collected);
        break;
      case "orders":
        partial = await readOrders(env, collected, job.sinceDay);
        break;
      case "traffic":
        await readTraffic(env, job.days ?? [], collected);
        break;
      case "order_income":
        partial = await readOrderIncome(env, job.orderIds ?? [], collected, job.orderSns, job);
        break;
      case "health":
        await readHealth(env, collected);
        break;
      case "affiliate":
        await readAffiliateConversions(env, collected, job.history);
        break;
      default: {
        const captures = AFFILIATE_CAPTURES[job.id];
        if (captures) await readAffiliateCaptured(env, captures, collected);
        break;
      }
    }
    return { status: "done", responses: collected, ...(partial ? { detail: partial } : {}) };
  } catch (error) {
    if (error instanceof Stop) return error.outcome;
    return fail("error", collected, String((error as Error)?.message ?? error).slice(0, 120));
  }
}

/** A `waitFor` over a real clock (the hook); tests inject their own. */
export function pollingWaitFor(
  sleep: (ms: number) => Promise<void>,
  now: () => number,
): (condition: () => boolean, ms: number) => Promise<boolean> {
  return async (condition, ms) => {
    const deadline = now() + ms;
    while (!condition()) {
      if (now() >= deadline) return false;
      await sleep(READER_POLL_MS);
    }
    return true;
  };
}
