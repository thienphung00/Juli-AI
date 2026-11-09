// Runs in the Seller Centre PAGE world (manifest content_scripts world: MAIN,
// document_start). It wraps fetch / XMLHttpRequest to read the page's OWN
// responses from the four /api/mydata endpoints the connector maps, and hands
// them to the content script with window.postMessage (target origin pinned to
// Seller Centre). The session params Seller Centre adds (SPC_CDS, SPC_CDS_VER) stay in this
// page's memory; they are used only to re-issue the same requests during the daily
// sync and are never sent to Juli.
//
// Page readers (ADR-120 d.14): for the nine report endpoints in READER_ENDPOINTS it also
// remembers how the PAGE called them (query, JSON request body, request headers) so a
// scheduled job can replay the page's own read-only query for one day / page number. Those
// templates, and the headers in them, stay in this page's memory like the session params;
// only the responses to the job's requests are handed to the content script. It reads no
// cookies, no other URLs, and sends nothing but those queries: it never clicks, applies or
// saves anything.

import { CHANNEL, FILL_HASH_KEY, READER_IDS, SELLER_CENTRE_ORIGIN } from "../config";
import { bundleIdFrom, savedBundlePath, savedVoucherPath, voucherIdFrom } from "../fill/saved";
import {
  isCapturedEndpoint,
  READER_ENDPOINTS,
  type ReaderEndpoint,
  readerEndpointOf,
  SESSION_PARAMS,
  WATCHED_PATHS,
} from "../shopee/endpoints";
import {
  blockedPath,
  pollingWaitFor,
  isPasswordPrompt,
  type ReaderEnv,
  type ReaderJob,
  type ReaderRequest,
  runReaderJob,
  type Template as ReaderTemplate,
  trimCaptured,
} from "../shopee/reader";
import { Pacer, runDay, type DayRequest } from "../shopee/runner";
import { type PlannedRequest, requestUrl } from "../shopee/sync";
import { gmt7Date } from "../shopee/time";

interface Template {
  params: Record<string, string>;
  day: string;
}

const session: Record<string, string> = {};
const templates = new Map<string, Template>();
// Every request this hook sends (daily sync and backfill) goes through one pacer:
// one plan at a time, ≥ 2 s + jitter between any two requests.
const pacer = new Pacer({
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now: () => Date.now(),
});

function today(): string {
  return gmt7Date(Math.floor(Date.now() / 1000));
}

function watched(rawUrl: string): URL | null {
  try {
    const url = new URL(rawUrl, location.href);
    if (url.origin !== SELLER_CENTRE_ORIGIN || !WATCHED_PATHS.has(url.pathname)) return null;
    return url;
  } catch {
    return null;
  }
}

function remember(url: URL): void {
  const params: Record<string, string> = {};
  url.searchParams.forEach((value, key) => {
    if ((SESSION_PARAMS as readonly string[]).includes(key)) session[key] = value;
    else params[key] = value;
  });
  templates.set(url.pathname, { params, day: today() });
}

function publicUrl(url: URL): string {
  const copy = new URL(url.toString());
  for (const key of SESSION_PARAMS) copy.searchParams.delete(key);
  return copy.toString();
}

function emit(url: URL, body: unknown): void {
  window.postMessage(
    { channel: CHANNEL, kind: "capture", url: publicUrl(url), body, capturedAt: Date.now() },
    SELLER_CENTRE_ORIGIN,
  );
}

// -- page reader templates ----------------------------------------------------------------

const readerTemplates = new Map<ReaderEndpoint, ReaderTemplate>();
/** Headers of the page's own /api/mydata calls (memory only): the template for traffic/details. */
let mydataHeaders: Record<string, string> | undefined;

function headersToRecord(headers: HeadersInit | undefined): Record<string, string> | undefined {
  if (!headers) return undefined;
  const out: Record<string, string> = {};
  if (headers instanceof Headers) headers.forEach((value, key) => (out[key] = value));
  else if (Array.isArray(headers)) for (const [key, value] of headers) out[key] = value;
  else Object.assign(out, headers);
  return out;
}

function parseJson(text: unknown): unknown {
  if (typeof text !== "string") return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

/** Remember how the page called a report endpoint (and the session params it carried). */
function learn(
  endpoint: ReaderEndpoint,
  url: URL,
  body: unknown,
  headers: Record<string, string> | undefined,
): void {
  const query: Record<string, string> = {};
  url.searchParams.forEach((value, key) => {
    if ((SESSION_PARAMS as readonly string[]).includes(key)) session[key] = value;
    else query[key] = value;
  });
  const previous = readerTemplates.get(endpoint);
  readerTemplates.set(endpoint, {
    query,
    ...(body !== undefined ? { body } : {}),
    ...(headers ? { headers } : {}),
    ...(previous?.lastResponse !== undefined ? { lastResponse: previous.lastResponse } : {}),
  });
}

function keepResponse(endpoint: ReaderEndpoint, body: unknown): void {
  // Only the answers of captured endpoints are kept (their requests are never replayed): the
  // campaign query and the affiliate pages' own reports. Trimmed to what a mapper may read.
  if (!isCapturedEndpoint(endpoint)) return;
  const template = readerTemplates.get(endpoint);
  if (template) template.lastResponse = trimCaptured(endpoint, body);
}

function readerTarget(rawUrl: string, method: string): { endpoint: ReaderEndpoint; url: URL } | null {
  try {
    const url = new URL(rawUrl, location.href);
    if (url.origin !== SELLER_CENTRE_ORIGIN) return null;
    const endpoint = readerEndpointOf(method, url.pathname, url.searchParams.get("q"));
    return endpoint ? { endpoint, url } : null;
  } catch {
    return null;
  }
}

// -- a voucher the person saved on a fill-job page (P97 D85.6) ----------------------------------

/** Only on a page opened by a fill job (`#juli-fill=...`): keep the new voucher_id / combo id of the create answer. */
function noteSavedVoucher(rawUrl: string, method: string, body: unknown): void {
  try {
    if (method !== "POST" || !location.hash.includes(`${FILL_HASH_KEY}=`)) return;
    const url = new URL(rawUrl, location.href);
    if (url.origin !== SELLER_CENTRE_ORIGIN) return;
    const ref = savedVoucherPath(url.pathname) ? voucherIdFrom(body) : savedBundlePath(url.pathname) ? bundleIdFrom(body) : null;
    if (ref) window.postMessage({ channel: CHANNEL, kind: "fill-saved", ref }, SELLER_CENTRE_ORIGIN);
  } catch {
    // not ours to report
  }
}

// -- fetch ----------------------------------------------------------------------------

const originalFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const reader = readerTarget(raw, method);
  if (reader) {
    // Before the call, so a page request that fails still teaches the template.
    learn(
      reader.endpoint,
      reader.url,
      parseJson(init?.body),
      headersToRecord(init?.headers ?? (input instanceof Request ? input.headers : undefined)),
    );
  }
  if (watched(raw)) {
    const seen = headersToRecord(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    if (seen) mydataHeaders = seen;
  }
  const response = await originalFetch(input, init);
  if (response.ok && method === "POST") {
    response
      .clone()
      .json()
      .then((body: unknown) => noteSavedVoucher(raw, method, body))
      .catch(() => undefined);
  }
  if (reader && response.ok) {
    response
      .clone()
      .json()
      .then((body: unknown) => keepResponse(reader.endpoint, body))
      .catch(() => undefined);
  }
  const url = method === "GET" ? watched(raw) : null;
  if (url && response.ok) {
    remember(url);
    response
      .clone()
      .json()
      .then((body: unknown) => emit(url, body))
      .catch(() => undefined);
  }
  return response;
};

// -- XMLHttpRequest -------------------------------------------------------------------

const xhrPosts = new WeakMap<XMLHttpRequest, string>();
const xhrUrls = new WeakMap<XMLHttpRequest, URL>();
const xhrWatchedHeaders = new WeakMap<XMLHttpRequest, Record<string, string>>();
const xhrReaders = new WeakMap<
  XMLHttpRequest,
  { endpoint: ReaderEndpoint; url: URL; headers: Record<string, string> }
>();
const originalOpen = XMLHttpRequest.prototype.open;
const originalSend = XMLHttpRequest.prototype.send;
const originalSetHeader = XMLHttpRequest.prototype.setRequestHeader;

XMLHttpRequest.prototype.setRequestHeader = function setRequestHeader(
  this: XMLHttpRequest,
  name: string,
  value: string,
): void {
  const reader = xhrReaders.get(this);
  if (reader) reader.headers[name] = value;
  const watchedHeaders = xhrWatchedHeaders.get(this);
  if (watchedHeaders) watchedHeaders[name] = value;
  originalSetHeader.call(this, name, value);
};

XMLHttpRequest.prototype.open = function open(
  this: XMLHttpRequest,
  method: string,
  url: string | URL,
  ...rest: unknown[]
): void {
  if (method.toUpperCase() === "POST") xhrPosts.set(this, String(url));
  const target = method.toUpperCase() === "GET" ? watched(String(url)) : null;
  if (target) {
    xhrUrls.set(this, target);
    xhrWatchedHeaders.set(this, {});
  }
  const reader = readerTarget(String(url), method);
  if (reader) xhrReaders.set(this, { ...reader, headers: {} });
  (originalOpen as (...args: unknown[]) => void).call(this, method, url, ...rest);
};

XMLHttpRequest.prototype.send = function send(
  this: XMLHttpRequest,
  body?: Document | XMLHttpRequestBodyInit | null,
): void {
  const posted = xhrPosts.get(this);
  if (posted) {
    this.addEventListener("load", () => {
      if (this.status < 200 || this.status >= 300) return;
      try {
        noteSavedVoucher(
          posted,
          "POST",
          this.responseType === "json" ? this.response : JSON.parse(typeof this.response === "string" ? this.response : this.responseText),
        );
      } catch {
        // not JSON
      }
    });
  }
  const reader = xhrReaders.get(this);
  if (reader) {
    learn(reader.endpoint, reader.url, parseJson(body), reader.headers);
    this.addEventListener("load", () => {
      if (this.status < 200 || this.status >= 300) return;
      try {
        keepResponse(
          reader.endpoint,
          this.responseType === "json"
            ? this.response
            : JSON.parse(typeof this.response === "string" ? this.response : this.responseText),
        );
      } catch {
        // not JSON
      }
    });
  }
  const url = xhrUrls.get(this);
  if (url) {
    const seen = xhrWatchedHeaders.get(this);
    if (seen && Object.keys(seen).length > 0) mydataHeaders = seen;
    this.addEventListener("load", () => {
      if (this.status < 200 || this.status >= 300) return;
      remember(url);
      try {
        const parsed: unknown =
          this.responseType === "json"
            ? this.response
            : JSON.parse(typeof this.response === "string" ? this.response : this.responseText);
        emit(url, parsed);
      } catch {
        // not JSON: nothing to read
      }
    });
  }
  originalSend.call(this, body ?? null);
};

// -- daily sync, asked for by the content script --------------------------------------

function reply(status: string, detail: Record<string, unknown> = {}): void {
  window.postMessage({ channel: CHANNEL, kind: "sync-result", status, ...detail }, SELLER_CENTRE_ORIGIN);
}

function hasSession(): boolean {
  return SESSION_PARAMS.every((key) => key in session);
}

async function runPlan(plan: PlannedRequest[]): Promise<void> {
  if (!hasSession()) {
    // The page has not made a data call in this tab yet: never invent the session params.
    return reply("needs_data_page");
  }
  let sent = 0;
  for (const request of plan) {
    if (!WATCHED_PATHS.has(request.path)) continue;
    const template = templates.get(request.path);
    const url = requestUrl(
      SELLER_CENTRE_ORIGIN,
      request,
      session,
      template && template.day === today() ? template.params : undefined,
    );
    if (!url) continue;
    await pacer.beforeRequest();
    // Through the wrapped fetch: the response is captured like the page's own.
    await window.fetch(url, { method: "GET", credentials: "include" }).catch(() => undefined);
    sent += 1;
  }
  reply("done", { sent });
}

// -- backfill, one day per request from the service worker ----------------------------

function replyBackfill(day: string, status: string, results: unknown[] = []): void {
  window.postMessage({ channel: CHANNEL, kind: "backfill-result", day, status, results }, SELLER_CENTRE_ORIGIN);
}

async function runBackfillDay(day: string, plan: PlannedRequest[]): Promise<void> {
  if (!hasSession()) return replyBackfill(day, "needs_data_page");
  const requests: DayRequest[] = [];
  for (const request of plan) {
    if (!WATCHED_PATHS.has(request.path) || request.useTemplate) continue;
    const url = requestUrl(SELLER_CENTRE_ORIGIN, request, session);
    if (!url) continue;
    requests.push({ dataset: request.dataset, url, publicUrl: publicUrl(new URL(url)) });
  }
  // The unwrapped fetch: the service worker posts these results itself (and
  // learns per request whether Seller Centre accepted the day), so they must not
  // also be captured passively.
  const results = await runDay(
    requests,
    pacer,
    (url) => originalFetch(url, { method: "GET", credentials: "include" }),
    () => Date.now(),
  );
  replyBackfill(day, "done", results);
}

// -- page readers, one job from the service worker -----------------------------------------

/** Seller Centre's /datacenter password re-confirmation modal. Read only; never typed into. */
function passwordModalVisible(): boolean {
  const dialogs = document.querySelectorAll("[role='dialog'], [class*='modal' i]");
  for (const node of dialogs) {
    if (isPasswordPrompt((node as HTMLElement).innerText ?? "")) return true;
  }
  return isPasswordPrompt(document.body?.innerText ?? "");
}

function captchaVisible(): boolean {
  return !!document.querySelector("iframe[src*='captcha' i], [id*='captcha' i], [class*='captcha' i]");
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

async function runReader(job: ReaderJob): Promise<void> {
  const env: ReaderEnv = {
    origin: SELLER_CENTRE_ORIGIN,
    pacer,
    now: () => Date.now(),
    session: () => ({ ...session }),
    hasSession,
    template: (endpoint) => readerTemplates.get(endpoint),
    waitFor: pollingWaitFor(sleep, () => Date.now()),
    // The unwrapped fetch: the answer goes to the service worker with the job's result.
    fetch: (request: ReaderRequest) =>
      originalFetch(request.url, {
        method: request.method,
        headers: request.headers,
        ...(request.body !== undefined ? { body: request.body } : {}),
        credentials: "include",
      }),
    captchaVisible,
    passwordModalVisible,
    mydataHeaders: () => mydataHeaders,
    pathname: () => location.pathname,
    // The shared daily request budget: what the service worker granted this job.
    ...(typeof job.budget === "number" ? { budget: { left: job.budget } } : {}),
    pause: sleep,
  };
  const outcome = await runReaderJob(job, env);
  window.postMessage(
    {
      channel: CHANNEL,
      kind: "reader-result",
      job: job.id,
      status: outcome.status,
      detail: outcome.detail,
      responses: outcome.responses,
    },
    SELLER_CENTRE_ORIGIN,
  );
}

window.addEventListener("message", (event: MessageEvent) => {
  if (event.source !== window || event.origin !== SELLER_CENTRE_ORIGIN) return;
  const data = event.data as { channel?: string; kind?: string; plan?: unknown; day?: unknown; job?: unknown };
  if (data?.channel === CHANNEL && data.kind === "reader-job" && isReaderJob(data.job)) {
    const job = data.job;
    void pacer.serial(() => runReader(job));
    return;
  }
  if (data?.channel !== CHANNEL || !Array.isArray(data.plan)) return;
  const plan = data.plan as PlannedRequest[];
  if (data.kind === "sync") void pacer.serial(() => runPlan(plan));
  else if (data.kind === "backfill" && typeof data.day === "string") {
    const day = data.day;
    void pacer.serial(() => runBackfillDay(day, plan));
  }
});

function isReaderJob(value: unknown): value is ReaderJob {
  const job = value as {
    id?: unknown;
    days?: unknown;
    itemIds?: unknown;
    campaignIds?: unknown;
    orderIds?: unknown;
    orderSns?: unknown;
    budget?: unknown;
  } | null;
  const digitList = (list: unknown) =>
    list === undefined || (Array.isArray(list) && list.every((id) => typeof id === "string" && /^\d{1,32}$/.test(id)));
  return (
    typeof job === "object" &&
    job !== null &&
    typeof job.id === "string" &&
    (READER_IDS as readonly string[]).includes(job.id) &&
    digitList(job.itemIds) &&
    digitList(job.campaignIds) &&
    digitList(job.orderIds) &&
    (job.orderSns === undefined || (Array.isArray(job.orderSns) && job.orderSns.every((sn) => typeof sn === "string" && /^[A-Za-z0-9]{0,40}$/.test(sn)))) &&
    (job.budget === undefined || (typeof job.budget === "number" && Number.isFinite(job.budget) && job.budget >= 0)) &&
    (job.days === undefined || (Array.isArray(job.days) && job.days.every((d) => typeof d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(d))))
  );
}
