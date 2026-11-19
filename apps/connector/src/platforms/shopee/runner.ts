// How the page hook sends planned Seller Centre requests (pure, unit-tested with
// injected fetch / sleep / clock): one plan at a time, and every request ≥ 2 s +
// jitter after the previous one, whichever plan it belonged to.

import type { MydataDataset } from "./config";
import { itemRowsIn } from "./map";
import { waitBefore } from "./sync";

export interface PacerDeps {
  sleep: (ms: number) => Promise<void>;
  now: () => number;
  random?: () => number;
}

export class Pacer {
  private lastSentAt: number | undefined;
  private chain: Promise<unknown> = Promise.resolve();

  constructor(private readonly deps: PacerDeps) {}

  /** Run `work` after every earlier piece of work has finished. */
  serial<T>(work: () => Promise<T>): Promise<T> {
    const next = this.chain.then(work, work);
    this.chain = next.catch(() => undefined);
    return next;
  }

  /** Wait until the next request may go, then count it as sent. */
  async beforeRequest(): Promise<void> {
    const ms = waitBefore(this.lastSentAt, this.deps.now(), this.deps.random);
    if (ms > 0) await this.deps.sleep(ms);
    this.lastSentAt = this.deps.now();
  }
}

export interface FetchedResponse {
  status: number;
  text(): Promise<string>;
}

/** One backfill request's outcome, as the service worker needs it. */
export interface RequestResult {
  dataset: MydataDataset;
  /** The request URL without the session params. */
  url: string;
  /** HTTP status; 0 = network failure. */
  status: number;
  /** Parsed JSON body, or null (network failure, or not JSON: a login page). */
  body: unknown;
  capturedAt: number;
}

export interface DayRequest {
  dataset: MydataDataset;
  /** The URL actually sent (with session params). */
  url: string;
  /** The same URL without session params (what is reported back). */
  publicUrl: string;
  /** One page of a paged list (see PlannedRequest.page). */
  page?: { group: string; pageSize: number };
}

/** How many rows a list answer carries (0 when none is found). */
export function pageRowCount(body: unknown): number {
  return itemRowsIn(isRecord(body) ? (body.result ?? body.data ?? body) : body)?.length ?? 0;
}
const isRecord = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** F4.8: Sản phẩm › Tổng quan answers a bare `{metric: {value, ratio}}` object (no code, no wrapper). */
export function isFlatMetrics(body: Record<string, unknown>): boolean {
  const values = Object.values(body);
  return (
    !("code" in body) &&
    !("error" in body) &&
    values.length > 0 &&
    values.every((v) => isRecord(v) && "value" in v)
  );
}

/**
 * True when Seller Centre answered with data: HTTP 2xx and `code: 0`, or (0.3.20) the same answer
 * as `{error: 0, data}` / `{data}` / `{result}` without a code.
 */
export function isDataAnswer(status: number, body: unknown): boolean {
  if (status < 200 || status >= 300 || typeof body !== "object" || body === null || Array.isArray(body)) return false;
  const b = body as { code?: unknown; error?: unknown; data?: unknown; result?: unknown };
  if (isFlatMetrics(body as Record<string, unknown>)) return true;
  if ("code" in b) return b.code === 0;
  if ("error" in b) return b.error === 0 && (b.data != null || b.result != null);
  return (typeof b.data === "object" && b.data !== null) || (typeof b.result === "object" && b.result !== null);
}

/**
 * Send one backfill day's requests through `pacer`, stopping at the first answer
 * that is not data (an error code, a refused session, a network failure): the
 * service worker decides what it means; the remaining calls are not sent.
 */
export async function runDay(
  requests: DayRequest[],
  pacer: Pacer,
  fetchImpl: (url: string) => Promise<FetchedResponse>,
  now: () => number,
): Promise<RequestResult[]> {
  const results: RequestResult[] = [];
  const exhausted = new Set<string>();
  for (const request of requests) {
    if (request.page && exhausted.has(request.page.group)) continue;
    await pacer.beforeRequest();
    let status = 0;
    let body: unknown = null;
    try {
      const response = await fetchImpl(request.url);
      status = response.status;
      try {
        body = JSON.parse(await response.text());
      } catch {
        body = null;
      }
    } catch {
      status = 0;
    }
    results.push({ dataset: request.dataset, url: request.publicUrl, status, body, capturedAt: now() });
    if (!isDataAnswer(status, body)) break;
    if (request.page && pageRowCount(body) < request.page.pageSize) exhausted.add(request.page.group);
  }
  return results;
}
