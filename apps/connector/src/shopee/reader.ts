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
  ORDER_LIST_MAX_PAGES_PER_RUN,
  ORDER_LIST_PAGE_GAP_JITTER_MS,
  ORDER_LIST_PAGE_GAP_MS,
  PRODUCT_MAX_PAGES,
  TRAFFIC_MAX_CONSECUTIVE_ERRORS,
  TRAFFIC_MAX_REQUESTS_PER_JOB,
  READER_POLL_MS,
  READER_TEMPLATE_WAIT_MS,
  type ReaderId,
  VOUCHER_MAX_ROWS,
  VOUCHER_PAGE_LIMIT_DEFAULT,
} from "../config";
import { isReadOnlyOrderPath, isReadOnlyPasPath, READER_ENDPOINTS, type ReaderEndpoint } from "./endpoints";
import { trimOrderCards, trimOrderIndex } from "./orders-map";
import type { Pacer } from "./runner";
import { gmt7Date, gmt7DateStart, lastFinishedDays } from "./time";

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
  /** order_income: the completed orders to read; the first is the order page the scheduler opened. */
  orderIds?: string[];
  /** order_income: per order, the order number that is hashed (parallel to `orderIds`; "" = unknown). */
  orderSns?: string[];
  /** Requests this job may still send (the shared daily budget's remainder). */
  budget?: number;
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
  /** HTTP 429 / 403 / a Shopee message that says "too many requests": stops every reader. */
  | "blocked_rate"
  /** The shared daily request budget is spent: the job stops, the rest waits for tomorrow. */
  | "budget_spent"
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
  const text = `${String(body.msg ?? "")} ${String(body.message ?? "")} ${typeof code === "string" ? code : ""}`;
  if (Number(code) === 429 || RATE_WORDS.test(text)) return "rate";
  return LOGIN_WORDS.test(text) ? "login" : "error";
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

/** The /datacenter re-confirmation modal's text (any dialog text is passed in). */
export function isPasswordPrompt(text: string): boolean {
  return /vui lòng nhập mật khẩu shopee/i.test(text);
}

/** `path` blocked by a login / verification page (client-side redirect or whole-tab redirect). */
export function blockedPath(pathname: string): "login" | "captcha" | null {
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
): Promise<ReaderResponse> {
  if (env.passwordModalVisible?.()) throw new Stop(fail("blocked_login", collected, "password_modal"));
  const wall = env.captchaVisible?.() ? "captcha" : blockedPath(env.pathname?.() ?? "");
  if (wall) throw new Stop(fail(wall === "captcha" ? "blocked_captcha" : "blocked_login", collected, "page"));
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
  const ready = () => env.hasSession() && need.every((endpoint) => env.template(endpoint) !== undefined);
  if (await env.waitFor(ready, READER_TEMPLATE_WAIT_MS)) return;
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

async function readAds(env: ReaderEnv, days: string[], collected: ReaderResponse[]): Promise<void> {
  await waitForPage(env, [], collected);
  // The page's own homepage query is the template; its graph query is optional.
  await env.waitFor(() => env.template("ads_homepage") !== undefined, READER_TEMPLATE_WAIT_MS / 2);
  await env.waitFor(() => env.template("ads_time_graph") !== undefined, 8_000);
  const home = env.template("ads_homepage");
  const graph = env.template("ads_time_graph");
  const homeBody = isRecord(home?.body) ? home.body : ADS_HOMEPAGE_FALLBACK;
  const limitNumber = Number(homeBody.limit);
  const limit = Number.isInteger(limitNumber) && limitNumber > 0 ? limitNumber : ADS_PAGE_LIMIT_DEFAULT;
  const usePaidGmv = homeBody.use_paid_gmv === true;
  if (days.length === 0) {
    // Connector 0.3.11: no day left to read, but the list's settings are refreshed once a day.
    // Read with yesterday's bounds and NO day tag, so no daily post is made from it.
    const bounds = dayBounds(gmt7Date(Math.floor(env.now() / 1000) - 86_400));
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
      const response = await send(env, request, collected, { page: offset / limit + 1, usePaidGmv });
      const found = findList(payloadOf(response.body), isAdsEntry);
      rows += found?.list.length ?? 0;
      if (!found || found.list.length < limit) break;
      const total = totalOf(response.body, found.parent);
      if (total !== undefined && rows >= total) break;
    }
    return;
  }
  for (const day of days) {
    const bounds = dayBounds(day);
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
      const response = await send(env, request, collected, { day, page: offset / limit + 1, usePaidGmv });
      const found = findList(payloadOf(response.body), isAdsEntry);
      rows += found?.list.length ?? 0;
      if (!found || found.list.length < limit) break;
      const total = totalOf(response.body, found.parent);
      if (total !== undefined && rows >= total) break;
    }
    if (graph) {
      const request = buildReaderRequest(env.origin, "ads_time_graph", graph, { body: bounds }, env.session());
      await send(env, request, collected, { day });
    }
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

/** Only the four source blocks of a traffic-details answer are kept (the funnel / pie data are not read). */
export function trimTrafficBody(body: unknown): unknown {
  if (!isRecord(body)) return body;
  const result = isRecord(body.result) ? body.result : isRecord(body.data) ? body.data : null;
  if (!result) return body;
  const kept: Record<string, unknown> = {};
  for (const key of ["product_card", "live", "video", "affiliate"]) {
    if (key in result) kept[key] = result[key];
  }
  return { code: body.code, result: kept };
}

/** A finished GMT+7 day as the mydata `period=day` picker sends it (end = next midnight). */
export function trafficDayBounds(day: string): { start_time: number; end_time: number } {
  const start = gmt7DateStart(day);
  return { start_time: start, end_time: start + 86_400 };
}

async function readItemTraffic(env: ReaderEnv, days: string[], itemIds: string[], collected: ReaderResponse[]): Promise<void> {
  // The re-confirmation modal means the page will never load its data: stop at once.
  const modal = () => env.passwordModalVisible?.() === true;
  const ready = await env.waitFor(() => modal() || env.hasSession(), READER_TEMPLATE_WAIT_MS);
  if (modal()) throw new Stop(fail("blocked_login", collected, "password_modal"));
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
  for (const day of days) {
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

/**
 * The order list: the page's OWN first answers are kept (trimmed in the page); pages 2..N are
 * replayed from the page's request templates, a pause of 20-45 s before each, at most
 * ORDER_LIST_MAX_PAGES_PER_RUN pages in all. Nothing is replayed when the page's request has no
 * recognisable page number or id list (then only what the page loaded is read).
 */
async function readOrders(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
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
  if (!search || !isRecord(search.body) || !isRecord(cards.body)) return;
  if (!isReadOnlyOrderPath(READER_ENDPOINTS.order_search.path) || !isReadOnlyOrderPath(READER_ENDPOINTS.order_cards.path)) return;
  const size = bodyPageSize(search.body) ?? pageSizeOf(search, 40);
  // The cards template still holds the FIRST page's ids: every later page swaps those out.
  const firstIds = orderIdsOf(search.lastResponse);
  const random = env.random ?? Math.random;
  for (let page = 2; page <= ORDER_LIST_MAX_PAGES_PER_RUN; page += 1) {
    const indexBody = withListPage(search.body, page, size);
    if (indexBody === null || firstIds.length === 0) return;
    await env.pause?.(ORDER_LIST_PAGE_GAP_MS + Math.floor(random() * ORDER_LIST_PAGE_GAP_JITTER_MS));
    const indexRequest = buildReaderRequest(env.origin, "order_search", search, { body: indexBody as Record<string, unknown> }, env.session());
    const index = await send(env, indexRequest, collected, { page });
    index.body = trimOrderIndex(index.body);
    const ids = orderIdsOf(index.body);
    if (ids.length === 0) return;
    const cardBody = withOrderIds(cards.body, firstIds, ids);
    if (cardBody === null) return;
    const cardRequest = buildReaderRequest(env.origin, "order_cards", cards, { body: cardBody as Record<string, unknown> }, env.session());
    const answer = await send(env, cardRequest, collected, { page });
    answer.body = trimOrderCards(answer.body);
    if (ids.length < size) return;
  }
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
 * Per-order income: the order page the scheduler opened is `ids[0]`: its own answer is kept; for
 * every other id the same GET is replayed with only the order id changed (one request each, at the
 * normal pace). A call whose template shows no order id is never replayed.
 */
async function readOrderIncome(env: ReaderEnv, ids: string[], collected: ReaderResponse[], sns: string[] = []): Promise<void> {
  const snOf = (index: number) => (sns[index] ? { orderSn: sns[index] } : {});
  await waitForPage(env, ["order_income_components"], collected);
  const template = env.template("order_income_components") as Template;
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
  if (!where) return;
  for (const [offset, id] of ids.slice(1).entries()) {
    const overrides = where.where === "query" ? { query: { [where.key]: id } } : { body: { [where.key]: id } };
    const request = buildReaderRequest(env.origin, "order_income_components", template, overrides, env.session());
    // An income answer that is not data (a refused order) is skipped; a rate stop still stops all.
    await send(env, request, collected, { orderId: id, ...snOf(offset + 1) }, true);
  }
}

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

async function readAffiliateConversions(env: ReaderEnv, collected: ReaderResponse[]): Promise<void> {
  // The conversion page's own call is the template. It often carries no SPC_CDS query,
  // so waiting on the session first ended the job as needs_data_page with nothing posted.
  const seen = () => env.template("affiliate_conversion") !== undefined;
  if (!(await env.waitFor(() => env.hasSession() || seen(), READER_TEMPLATE_WAIT_MS))) {
    throw new Stop(fail("needs_data_page", collected, "affiliate_conversion"));
  }
  await env.waitFor(seen, READER_TEMPLATE_WAIT_MS / 2);
  const template = env.template("affiliate_conversion");
  const days = lastFinishedDays(env.now(), AFFILIATE_WINDOW_DAYS);
  if (days.length === 0) return;
  const sorted = [...days].sort();
  const period = { start: sorted[0] as string, end: sorted[sorted.length - 1] as string };
  const window = {
    purchase_time_s: String(gmt7DateStart(period.start)),
    purchase_time_e: String(gmt7DateStart(period.end) + 86_399),
  };
  const size = template ? pageSizeOf(template, AFFILIATE_PAGE_SIZE_DEFAULT) : AFFILIATE_PAGE_SIZE_DEFAULT;
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
  try {
    switch (job.id) {
      case "products":
        await readProducts(env, collected);
        break;
      case "item_traffic":
        await readItemTraffic(env, job.days ?? [], job.itemIds ?? [], collected);
        break;
      case "ads":
        await readAds(env, job.days ?? [], collected);
        break;
      case "ads_detail":
        await readAdsDetail(env, job.campaignIds ?? [], collected);
        break;
      case "vouchers":
        await readVouchers(env, collected);
        break;
      case "shop_totals":
        await readShopTotals(env, job.days ?? [], collected);
        break;
      case "orders":
        await readOrders(env, collected);
        break;
      case "order_income":
        await readOrderIncome(env, job.orderIds ?? [], collected, job.orderSns);
        break;
      case "health":
        await readHealth(env, collected);
        break;
      case "affiliate":
        await readAffiliateConversions(env, collected);
        break;
      default: {
        const captures = AFFILIATE_CAPTURES[job.id];
        if (captures) await readAffiliateCaptured(env, captures, collected);
        break;
      }
    }
    return { status: "done", responses: collected };
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
