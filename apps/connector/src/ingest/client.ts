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
  period: { start: string; end: string; granularity: "day" };
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
    period: { start: mapped.date, end: mapped.date, granularity: "day" },
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

  post(token: string, dataset: Dataset, body: IngestBody): Promise<unknown> {
    return this.call(`/v1/ingest/shopee/${dataset}`, { method: "POST", body: JSON.stringify(body) }, token);
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
