import type { Critical, Matrix, Overview, ProductPage, Ranking } from "./types";

/**
 * The one client of the Shopee shop read APIs. The SAME screens run for the seller
 * (`/v1/demo/shopee/*`, bearer + `X-Shop-Id`) and for Juli Ops (`/v1/ops/shops/{id}/shopee/analytics/*`,
 * bearer only, read-only): only the base and the headers differ, so a screen takes a
 * {@link ShopeeApi} and never knows which one it holds. Every call is a GET.
 */

export const DEMO_SHOPEE_BASE = "/v1/demo/shopee" as const;

export function opsShopeeBase(shopId: string): string {
  return `/v1/ops/shops/${encodeURIComponent(shopId)}/shopee/analytics`;
}

export type PeriodKind = "7d" | "30d" | "90d" | "month" | "custom";

/** The window the API resolves (ending on the newest day with data unless `asOf`). */
export interface WindowQuery {
  readonly period: PeriodKind;
  readonly month?: string | null;
  readonly from?: string | null;
  readonly to?: string | null;
}

export interface RankingQuery extends WindowQuery {
  readonly kind?: string;
  readonly source?: string;
  readonly sub?: string | null;
  readonly xepTheo?: string;
}

export interface MatrixQuery extends WindowQuery {
  readonly sort?: "gmv" | "bien" | "orders" | "profit";
  readonly limit?: number;
}

export interface ShopeeApi {
  overview(q: WindowQuery): Promise<Overview>;
  matrix(q: MatrixQuery): Promise<Matrix>;
  critical(q: WindowQuery): Promise<Critical>;
  ranking(q: RankingQuery): Promise<Ranking>;
  product(itemId: string, period: "7d" | "30d" | "90d"): Promise<ProductPage>;
}

export class ShopeeApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    /** The `detail` object of the refusal (P91: the `breaches` of a 422 that needs a yes). */
    public readonly detail?: Readonly<Record<string, unknown>>,
  ) {
    super(message);
    this.name = "ShopeeApiError";
  }
}

export type ApiRefusal = "not-shopee" | "no-data" | "not-found" | "invalid" | "failed";

/** What a refusal means to a screen (the codes of `shopee_analytics_common.refusal`). */
export function refusalOf(error: unknown): ApiRefusal {
  if (!(error instanceof ShopeeApiError)) return "failed";
  if (error.code === "not_a_shopee_shop") return "not-shopee";
  if (error.code === "no_shopee_data") return "no-data";
  if (error.code === "product_not_found" || error.status === 404) return "not-found";
  if (error.status === 422) return "invalid";
  return "failed";
}

function windowParams(q: WindowQuery): URLSearchParams {
  const p = new URLSearchParams();
  p.set("period", q.period);
  if (q.period === "month" && q.month) p.set("month", q.month);
  if (q.period === "custom") {
    if (q.from) p.set("from", q.from);
    if (q.to) p.set("to", q.to);
  }
  return p;
}

function errorOf(status: number, payload: unknown): ShopeeApiError {
  let code = "";
  let message = `HTTP ${status}`;
  if (typeof payload === "object" && payload !== null && "detail" in payload) {
    const detail = (payload as { detail: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (typeof detail === "object" && detail !== null) {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string") message = d.message;
    }
  }
  return new ShopeeApiError(status, code, message);
}

export interface ShopeeClientOptions {
  /** `DEMO_SHOPEE_BASE` or `opsShopeeBase(shopId)`. */
  readonly base: string;
  readonly token: string;
  /** Seller scope only: the acting shop (`X-Shop-Id`). */
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

export function createShopeeApi(options: ShopeeClientOptions): ShopeeApi {
  const { base, token, shopId, fetchImpl } = options;
  async function get<T>(path: string, params: URLSearchParams): Promise<T> {
    const doFetch = fetchImpl ?? fetch;
    const qs = params.toString();
    const response = await doFetch(`${base}${path}${qs ? `?${qs}` : ""}`, {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(shopId ? { "X-Shop-Id": shopId } : {}),
      },
      cache: "no-store",
    });
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) throw errorOf(response.status, payload);
    return payload as T;
  }
  return {
    overview: (q) => get<Overview>("/overview", windowParams(q)),
    matrix: (q) => {
      const p = windowParams(q);
      if (q.sort) p.set("sort", q.sort);
      if (q.limit) p.set("limit", String(q.limit));
      return get<Matrix>("/matrix", p);
    },
    critical: (q) => get<Critical>("/critical", windowParams(q)),
    ranking: (q) => {
      const p = windowParams(q);
      p.set("kind", q.kind ?? "products");
      p.set("source", q.source ?? "all");
      if (q.sub) p.set("sub", q.sub);
      p.set("xep_theo", q.xepTheo ?? "gmv_per_day");
      return get<Ranking>("/ranking", p);
    },
    product: (itemId, period) =>
      get<ProductPage>(`/products/${encodeURIComponent(itemId)}`, new URLSearchParams({ period })),
  };
}
