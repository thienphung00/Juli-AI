// Runs in the Seller Centre PAGE world (manifest content_scripts world: MAIN,
// document_start). It wraps fetch / XMLHttpRequest to read the page's OWN
// responses from the four /api/mydata endpoints the connector maps, and hands
// them to the content script with window.postMessage (target origin pinned to
// Seller Centre). It reads nothing else: no cookies, no request bodies, no other
// URLs. The session params Seller Centre adds (SPC_CDS, SPC_CDS_VER) stay in this
// page's memory; they are used only to re-issue the same GETs during the daily
// sync and are never sent to Juli.

import { CHANNEL, SELLER_CENTRE_ORIGIN } from "../config";
import { SESSION_PARAMS, WATCHED_PATHS } from "../shopee/endpoints";
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

// -- fetch ----------------------------------------------------------------------------

const originalFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const response = await originalFetch(input, init);
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
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

const xhrUrls = new WeakMap<XMLHttpRequest, URL>();
const originalOpen = XMLHttpRequest.prototype.open;
const originalSend = XMLHttpRequest.prototype.send;

XMLHttpRequest.prototype.open = function open(
  this: XMLHttpRequest,
  method: string,
  url: string | URL,
  ...rest: unknown[]
): void {
  const target = method.toUpperCase() === "GET" ? watched(String(url)) : null;
  if (target) xhrUrls.set(this, target);
  (originalOpen as (...args: unknown[]) => void).call(this, method, url, ...rest);
};

XMLHttpRequest.prototype.send = function send(
  this: XMLHttpRequest,
  body?: Document | XMLHttpRequestBodyInit | null,
): void {
  const url = xhrUrls.get(this);
  if (url) {
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

window.addEventListener("message", (event: MessageEvent) => {
  if (event.source !== window || event.origin !== SELLER_CENTRE_ORIGIN) return;
  const data = event.data as { channel?: string; kind?: string; plan?: unknown; day?: unknown };
  if (data?.channel !== CHANNEL || !Array.isArray(data.plan)) return;
  const plan = data.plan as PlannedRequest[];
  if (data.kind === "sync") void pacer.serial(() => runPlan(plan));
  else if (data.kind === "backfill" && typeof data.day === "string") {
    const day = data.day;
    void pacer.serial(() => runBackfillDay(day, plan));
  }
});
