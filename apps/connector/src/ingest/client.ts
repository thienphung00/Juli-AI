// The Juli ingest gateway client (runs in the service worker). The token is the
// only credential the extension holds: no Juli password, no Juli session.

import { API_ORIGIN, type Dataset } from "../config";
import type { Drift, Mapped } from "../shopee/map";

export interface TokenInfo {
  token: string;
  token_id: string;
  shop_id: string;
  platform: string;
  expires_at: string;
  rotate_after: string;
}

export interface IngestBody {
  source: "extension";
  source_version: string;
  captured_at: string;
  period: { start: string; end: string; granularity: "day" | "period" };
  order_type: string | null;
  platform_shop_id?: string;
  rows: Record<string, unknown>[];
}

export class GatewayError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
  ) {
    super(`${status} ${code}`);
  }
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** The post the gateway expects for one mapped response. */
export function ingestBody(mapped: Mapped, version: string, capturedAt: number, shopeeShopId?: string): IngestBody {
  const body: IngestBody = {
    source: "extension",
    source_version: version,
    captured_at: new Date(capturedAt).toISOString(),
    period: { start: mapped.periodStart ?? mapped.date, end: mapped.date, granularity: mapped.granularity ?? "day" },
    order_type: mapped.orderType,
    rows: mapped.rows,
  };
  if (shopeeShopId) body.platform_shop_id = shopeeShopId;
  return body;
}

export class GatewayClient {
  constructor(
    private readonly fetchImpl: FetchLike = (input, init) => fetch(input, init),
    private readonly origin: string = API_ORIGIN,
  ) {}

  private async call(path: string, init: RequestInit, token?: string): Promise<unknown> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await this.fetchImpl(`${this.origin}${path}`, {
      ...init,
      headers,
      credentials: "omit",
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = (payload as { detail?: { code?: string } } | null)?.detail;
      throw new GatewayError(response.status, detail?.code ?? "http_error");
    }
    return payload;
  }

  pair(code: string, clientLabel: string, shopeeShopId?: string): Promise<TokenInfo> {
    return this.call("/v1/ingest/pair", {
      method: "POST",
      body: JSON.stringify({
        code,
        platform: "shopee",
        client_label: clientLabel,
        ...(shopeeShopId ? { platform_shop_id: shopeeShopId } : {}),
      }),
    }) as Promise<TokenInfo>;
  }

  rotate(token: string): Promise<TokenInfo> {
    return this.call("/v1/ingest/token/rotate", { method: "POST" }, token) as Promise<TokenInfo>;
  }

  status(token: string): Promise<unknown> {
    return this.call("/v1/ingest/status", { method: "GET" }, token);
  }

  /** The approved text of one card for the listing fill-in (read-only; p91 D-13). */
  fillRequest(token: string, code: string): Promise<unknown> {
    return this.call(`/v1/ingest/fill/${encodeURIComponent(code)}`, { method: "GET" }, token);
  }

  /** The open fill jobs of the token's shop (P97 D85.6). Juli serves nothing while its kill switch is off. */
  fillJobs(token: string): Promise<unknown> {
    return this.call("/v1/ingest/fill-jobs", { method: "GET" }, token);
  }

  /** How far one fill job got: opened / filled / saved / captured (with the new id) / failed. */
  fillJobReport(token: string, jobId: string, body: { status: string; captured_ref?: string; error?: string }): Promise<unknown> {
    return this.call(`/v1/ingest/fill-jobs/${encodeURIComponent(jobId)}`, { method: "POST", body: JSON.stringify(body) }, token);
  }

  /** The keywords of the shop's products to read on the public search page (P92 B-10). */
  marketKeywords(token: string): Promise<unknown> {
    return this.call("/v1/ingest/market/keywords", { method: "GET" }, token);
  }

  /** The shop's order_ref key (affiliate reader): order ids are hashed with it in the browser. */
  orderRefKey(token: string): Promise<unknown> {
    return this.call("/v1/ingest/order-ref-key", { method: "GET" }, token);
  }

  post(token: string, dataset: Dataset, body: IngestBody): Promise<unknown> {
    return this.call(`/v1/ingest/shopee/${dataset}`, { method: "POST", body: JSON.stringify(body) }, token);
  }

  /** A stop that halts every reader (CAPTCHA, login wall, 429 / 403): reader, page, status, time. */
  connectorEvent(
    token: string,
    event: { reader: string; page: string; status: string; code?: string; at: string },
    version: string,
  ): Promise<unknown> {
    return this.call(
      "/v1/ingest/connector-events",
      {
        method: "POST",
        body: JSON.stringify({
          platform: "shopee",
          reader: event.reader,
          page: event.page.slice(0, 120),
          status: event.status,
          ...(event.code ? { code: event.code.slice(0, 40) } : {}),
          occurred_at: event.at,
          source_version: version,
        }),
      },
      token,
    );
  }

  reportDrift(
    token: string,
    dataset: Dataset,
    version: string,
    endpoint: string,
    drift: Drift | null,
  ): Promise<unknown> {
    return this.call(
      "/v1/ingest/status",
      {
        method: "POST",
        body: JSON.stringify({
          platform: "shopee",
          dataset,
          state: drift ? "drift" : "ok",
          source_version: version,
          endpoint,
          unexpected: drift?.unexpected.slice(0, 100) ?? [],
          missing: drift?.missing.slice(0, 100) ?? [],
        }),
      },
      token,
    );
  }
}
