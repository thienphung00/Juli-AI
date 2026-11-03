// The page readers' request side (pure, unit-tested with injected fetch / sleep / clock):
// given the request templates the page hook has learned from the page's OWN calls, replay them
// for one reader job (product list pages, one ads day, voucher pages, account health) at
// ≥ 2 s + jitter per request, and stop on a CAPTCHA / login wall.
//
// Read-only: every request is a GET, or one of the page's own POST *queries* (its report
// endpoints) with only a day / page number changed. Nothing here creates, applies or saves.

import {
  ADS_MAX_ROWS_PER_DAY,
  ADS_PAGE_LIMIT_DEFAULT,
  PRODUCT_MAX_PAGES,
  READER_POLL_MS,
  READER_TEMPLATE_WAIT_MS,
  type ReaderId,
  VOUCHER_MAX_ROWS,
  VOUCHER_PAGE_LIMIT_DEFAULT,
} from "../config";
import { READER_ENDPOINTS, type ReaderEndpoint } from "./endpoints";
import type { Pacer } from "./runner";
import { gmt7DateStart } from "./time";

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
  source: "replay" | "page";
  /** Ads: the request asked for paid (not placed) orders. */
  usePaidGmv?: boolean;
}

export type ReaderStatus =
  | "done"
  | "needs_data_page"
  | "needs_template"
  | "blocked_captcha"
  | "blocked_login"
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
  /** The tab's current path (a client-side redirect to a login or verification page). */
  pathname?: () => string;
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

type Verdict = "ok" | "login" | "captcha" | "error";

/** Shopee's anti-fraud refusal: HTTP 403 with this error code (a CAPTCHA / verification is due). */
const ANTI_FRAUD_CODE = 90309999;
const LOGIN_WORDS = /login|logged|sign.?in|session|auth|expired/i;

export function classify(status: number, body: unknown): Verdict {
  if (status === 401) return "login";
  if (status === 403) {
    if (isRecord(body) && body.error !== undefined && Number(body.error) !== ANTI_FRAUD_CODE) return "error";
    return "captcha";
  }
  if (status < 200 || status >= 300) return "error";
  if (!isRecord(body)) return "login"; // a login page instead of JSON
  const code = body.code ?? body.error;
  if (code === undefined || code === 0 || code === "0" || code === null) return "ok";
  const text = `${String(body.msg ?? "")} ${String(body.message ?? "")} ${typeof code === "string" ? code : ""}`;
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
): Promise<ReaderResponse> {
  const wall = env.captchaVisible?.() ? "captcha" : blockedPath(env.pathname?.() ?? "");
  if (wall) throw new Stop(fail(wall === "captcha" ? "blocked_captcha" : "blocked_login", collected, "page"));
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

/** Run one reader job against the open Seller Centre page. Never throws. */
export async function runReaderJob(job: ReaderJob, env: ReaderEnv): Promise<ReaderOutcome> {
  const collected: ReaderResponse[] = [];
  try {
    switch (job.id) {
      case "products":
        await readProducts(env, collected);
        break;
      case "ads":
        await readAds(env, job.days ?? [], collected);
        break;
      case "vouchers":
        await readVouchers(env, collected);
        break;
      case "health":
        await readHealth(env, collected);
        break;
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
