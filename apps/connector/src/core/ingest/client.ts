// The Juli ingest gateway client (runs in the service worker). The token is the
// only credential the extension holds: no Juli password, no Juli session.

import { API_ORIGIN } from "../config";

/** Fields seen / missing against the recorded shape of an answer (a platform's drift report). */
export interface Drift {
  unexpected: string[];
  missing: string[];
}

/** What `ingestBody` needs of a platform's mapped answer. */
export interface MappedPost {
  date: string;
  periodStart?: string;
  granularity?: "day" | "period";
  orderType: string | null;
  rows: Record<string, unknown>[];
}

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

/**
 * Who this install is, for every call: the version it sends in `X-Connector-Version` (Juli refuses
 * a version below its minimum with 426 `connector_upgrade_required`), its random per-install id
 * (sent at pairing: a re-pair from the same install supersedes the older token) and what to do when
 * Juli asks for an upgrade. Set once by the service worker; unset (tests) sends neither.
 */
export interface ClientIdentity {
  version?: string;
  installId?: () => Promise<string>;
  onUpgradeRequired?: (minimum: string) => void;
  /** batch-1124-a C3: Juli refused this token (401): the pairing that holds it stops by itself. */
  onTokenDead?: (token: string, code: string) => void;
}
let identity: ClientIdentity = {};
export function configureClientIdentity(next: ClientIdentity): void {
  identity = next;
}

/** The per-install id: random, created once, kept in storage. */
export async function loadInstallId(storage: {
  get(keys: string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
}): Promise<string> {
  const stored = (await storage.get([INSTALL_ID_KEY]))[INSTALL_ID_KEY];
  if (typeof stored === "string" && stored.length >= 8) return stored;
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const id = `i_${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
  await storage.set({ [INSTALL_ID_KEY]: id });
  return id;
}
export const INSTALL_ID_KEY = "installId";

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** The post the gateway expects for one mapped response. */
export function ingestBody(mapped: MappedPost, version: string, capturedAt: number, platformShopId?: string): IngestBody {
  const body: IngestBody = {
    source: "extension",
    source_version: version,
    captured_at: new Date(capturedAt).toISOString(),
    period: { start: mapped.periodStart ?? mapped.date, end: mapped.date, granularity: mapped.granularity ?? "day" },
    order_type: mapped.orderType,
    rows: mapped.rows,
  };
  if (platformShopId) body.platform_shop_id = platformShopId;
  return body;
}

/**
 * One platform's view of the gateway: the platform (a pack id) goes into the pairing request, the
 * ingest path and every report. A platform pack binds its own id (platforms/<id>/ingest/client).
 */
export class IngestClient {
  constructor(
    readonly platform: string,
    private readonly fetchImpl: FetchLike = (input, init) => fetch(input, init),
    private readonly origin: string = API_ORIGIN,
  ) {}

  private async call(path: string, init: RequestInit, token?: string): Promise<unknown> {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (identity.version) headers["X-Connector-Version"] = identity.version;
    const response = await this.fetchImpl(`${this.origin}${path}`, {
      ...init,
      headers,
      credentials: "omit",
    });
    const payload: unknown = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = (payload as { detail?: { code?: string; minimum?: string } } | null)?.detail;
      if (response.status === 426 && detail?.code === "connector_upgrade_required" && detail.minimum) {
        identity.onUpgradeRequired?.(detail.minimum);
      }
      if (response.status === 401 && token) identity.onTokenDead?.(token, detail?.code ?? "http_error");
      throw new GatewayError(response.status, detail?.code ?? "http_error");
    }
    return payload;
  }

  async pair(code: string, clientLabel: string, platformShopId?: string): Promise<TokenInfo> {
    const installId = await identity.installId?.().catch(() => undefined);
    return this.call("/v1/ingest/pair", {
      method: "POST",
      body: JSON.stringify({
        code,
        platform: this.platform,
        client_label: clientLabel,
        ...(installId ? { install_id: installId } : {}),
        ...(platformShopId ? { platform_shop_id: platformShopId } : {}),
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
  fillJobs(token: string, query: { scOpen?: boolean; ack?: string } = {}): Promise<unknown> {
    const qs = new URLSearchParams();
    if (query.scOpen !== undefined) qs.set("sc_open", query.scOpen ? "true" : "false");
    if (query.ack) qs.set("ack", query.ack);
    return this.call(`/v1/ingest/fill-jobs${qs.size ? `?${qs.toString()}` : ""}`, { method: "GET" }, token);
  }

  /** How far one fill job got: opened / filled / saved / captured (with the new id) / failed. */
  fillJobReport(
    token: string,
    jobId: string,
    body: {
      status: string;
      captured_ref?: string;
      error?: string;
      progress?: { filled: number; total: number };
      before_values?: Record<string, string>;
      period_ok?: boolean;
      fields?: { key: string; ok: boolean; seen: string }[];
    },
  ): Promise<unknown> {
    return this.call(`/v1/ingest/fill-jobs/${encodeURIComponent(jobId)}`, { method: "POST", body: JSON.stringify(body) }, token);
  }

  /** The keywords of the shop's products to read on the public search page (P92 B-10). */
  marketKeywords(token: string): Promise<unknown> {
    return this.call("/v1/ingest/market/keywords", { method: "GET" }, token);
  }

  /** 0.3.29 (F4.2, contract C2): per daily dataset, the days of the last 30 with no accepted row. */
  readDays(token: string): Promise<unknown> {
    return this.call(`/v1/connector/${this.platform}/read-days`, { method: "GET" }, token);
  }

  /** The shop's order_ref key (affiliate reader): order ids are hashed with it in the browser. */
  orderRefKey(token: string): Promise<unknown> {
    return this.call("/v1/ingest/order-ref-key", { method: "GET" }, token);
  }

  post(token: string, dataset: string, body: IngestBody): Promise<unknown> {
    return this.call(`/v1/ingest/${this.platform}/${dataset}`, { method: "POST", body: JSON.stringify(body) }, token);
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
          platform: this.platform,
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

  /**
   * The scheduler's last tick (0.3.19): what woke it, how it ended, and per report page how it
   * went (outcome notes are endpoint + HTTP status only). Metadata only, never a body.
   */
  connectorTick(
    token: string,
    report: { kind: string; trigger: string; result: string; day: string; at: string; outcomes?: Record<string, string> },
    version: string,
  ): Promise<unknown> {
    const outcomes = Object.fromEntries(
      Object.entries(report.outcomes ?? {})
        .slice(0, 40)
        .map(([reader, outcome]) => [reader.slice(0, 48), String(outcome).slice(0, 160)]),
    );
    return this.call(
      "/v1/ingest/connector-ticks",
      {
        method: "POST",
        body: JSON.stringify({
          platform: this.platform,
          kind: report.kind,
          trigger: report.trigger.slice(0, 32),
          result: report.result.slice(0, 80),
          day: report.day,
          occurred_at: report.at,
          outcomes,
          source_version: version,
        }),
      },
      token,
    );
  }

  reportDrift(
    token: string,
    dataset: string,
    version: string,
    endpoint: string,
    drift: Drift | null,
  ): Promise<unknown> {
    return this.call(
      "/v1/ingest/status",
      {
        method: "POST",
        body: JSON.stringify({
          platform: this.platform,
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
