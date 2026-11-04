import { ShopeeApiError, windowParams, type WindowQuery } from "../shopee-analytics/client";
import type { KolApi, KolProductReport, KolQuery, KolReport } from "./types";

export interface KolClientOptions {
  /** `DEMO_SHOPEE_BASE` or `opsShopeeBase(shopId)`; the reports are `<base>/kols` and `<base>/products/{item_id}/kols`. */
  readonly base: string;
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

const DEFAULT_WINDOW: WindowQuery = { period: "30d" };

async function get<T>(options: KolClientOptions, path: string, params: URLSearchParams): Promise<T> {
  const response = await (options.fetchImpl ?? fetch)(`${options.base}${path}?${params.toString()}`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${options.token}`,
      ...(options.shopId ? { "X-Shop-Id": options.shopId } : {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let code = "";
    let message = `HTTP ${response.status}`;
    try {
      const detail = ((await response.json()) as { detail?: unknown }).detail;
      if (typeof detail === "string") message = detail;
      else if (detail && typeof detail === "object") {
        const d = detail as { code?: unknown; message?: unknown };
        if (typeof d.code === "string") code = d.code;
        if (typeof d.message === "string") message = d.message;
      }
    } catch {
      /* keep the generic sentence */
    }
    throw new ShopeeApiError(response.status, code, message);
  }
  return (await response.json()) as T;
}

export function createKolApi(options: KolClientOptions): KolApi {
  return {
    report: (q: KolQuery = {}) => {
      const p = windowParams(q.window ?? DEFAULT_WINDOW);
      if (q.channel) p.set("channel", q.channel);
      if (q.itemId) p.set("item_id", q.itemId);
      if (q.kol) p.set("kol", q.kol);
      if (q.sort) p.set("sort", q.sort);
      if (q.limit) p.set("limit", String(q.limit));
      return get<KolReport>(options, "/kols", p);
    },
    productReport: (itemId, window = DEFAULT_WINDOW) => get<KolProductReport>(options, `/products/${encodeURIComponent(itemId)}/kols`, windowParams(window)),
  };
}
