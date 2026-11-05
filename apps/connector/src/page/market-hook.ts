// Runs in the PAGE world of https://shopee.vn/search* (manifest: MAIN, document_start). It wraps
// fetch / XMLHttpRequest and keeps ONE thing: the page's own page-1 search-items answer
// (`searchCall`), cut down to the public card fields (`trimSearchBody`). It sends no request of its
// own, reads no cookie / storage / other URL, clicks nothing, and logs nothing in. The answer goes
// to the relay content script with window.postMessage (target origin pinned to shopee.vn).

import { MARKET_CHANNEL, MARKET_ORIGIN } from "../config";
import { searchCall, trimSearchBody } from "../shopee/market";

function emit(url: string, status: number, body: unknown): void {
  const call = searchCall(url);
  if (!call) return;
  window.postMessage(
    {
      channel: MARKET_CHANNEL,
      kind: "market-answer",
      keyword: call.keyword,
      status,
      body: status >= 200 && status < 300 ? trimSearchBody(body) : null,
      capturedAt: Date.now(),
    },
    MARKET_ORIGIN,
  );
}

const originalFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
  const raw = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  const response = await originalFetch(input, init);
  if (searchCall(raw)) {
    response
      .clone()
      .json()
      .then((body: unknown) => emit(raw, response.status, body))
      .catch(() => emit(raw, response.status, null));
  }
  return response;
};

const xhrUrls = new WeakMap<XMLHttpRequest, string>();
const originalOpen = XMLHttpRequest.prototype.open;
XMLHttpRequest.prototype.open = function open(this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]): void {
  if (method.toUpperCase() === "GET" && searchCall(String(url))) xhrUrls.set(this, String(url));
  (originalOpen as (...args: unknown[]) => void).call(this, method, url, ...rest);
};
const originalSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.send = function send(this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null): void {
  const url = xhrUrls.get(this);
  if (url) {
    this.addEventListener("loadend", () => {
      let parsed: unknown = null;
      try {
        parsed =
          this.responseType === "json" ? this.response : JSON.parse(typeof this.response === "string" ? this.response : this.responseText);
      } catch {
        parsed = null;
      }
      emit(url, this.status, parsed);
    });
  }
  originalSend.call(this, body ?? null);
};
