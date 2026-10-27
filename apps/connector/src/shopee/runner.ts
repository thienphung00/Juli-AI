// How the page hook sends planned Seller Centre requests (pure, unit-tested with
// injected fetch / sleep / clock): one plan at a time, and every request ≥ 2 s +
// jitter after the previous one, whichever plan it belonged to.

import type { Dataset } from "../config";
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
  dataset: Dataset;
  /** The request URL without the session params. */
  url: string;
  /** HTTP status; 0 = network failure. */
  status: number;
  /** Parsed JSON body, or null (network failure, or not JSON: a login page). */
  body: unknown;
  capturedAt: number;
}

export interface DayRequest {
  dataset: Dataset;
  /** The URL actually sent (with session params). */
  url: string;
  /** The same URL without session params (what is reported back). */
  publicUrl: string;
}

/** True when Seller Centre answered with data (HTTP 2xx and `code: 0`). */
export function isDataAnswer(status: number, body: unknown): boolean {
  return status >= 200 && status < 300 && typeof body === "object" && body !== null && (body as { code?: unknown }).code === 0;
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
  for (const request of requests) {
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
  }
  return results;
}
