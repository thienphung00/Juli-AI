import { ShopeeApiError } from "../shopee-analytics/client";
import { fileToBase64 } from "../shop-inputs/api";
import type { KolApi, KolReport, KolSamplesApi, KolSamplesApplied, KolSamplesOverview, KolSamplesPreview } from "./types";

export interface KolClientOptions {
  /** `DEMO_SHOPEE_BASE` or `opsShopeeBase(shopId)`; the report is `<base>/kol`. */
  readonly base: string;
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

async function request(options: KolClientOptions, path: string, init: { method?: string; body?: unknown } = {}): Promise<Response> {
  const response = await (options.fetchImpl ?? fetch)(`${options.base}${path}`, {
    method: init.method ?? "GET",
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${options.token}`,
      ...(init.body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(options.shopId ? { "X-Shop-Id": options.shopId } : {}),
    },
    ...(init.body !== undefined ? { body: JSON.stringify(init.body) } : {}),
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
  return response;
}

export function createKolApi(options: KolClientOptions): KolApi {
  return { report: async () => (await (await request(options, "/kol")).json()) as KolReport };
}

/** `base` is `/v1/demo/shop-inputs` or `/v1/ops/shops/{id}/inputs`; envelopes are `{data}` like the SKU sheet's. */
export function createKolSamplesApi(options: KolClientOptions): KolSamplesApi {
  const data = async <T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> => ((await (await request(options, path, init)).json()) as { data: T }).data;
  return {
    overview: () => data<KolSamplesOverview>("/kol-samples"),
    template: async () => {
      const response = await request(options, "/kol-samples/template");
      const name = /filename="?([^";]+)"?/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? "mau-kol.xlsx";
      return { blob: await response.blob(), filename: name };
    },
    preview: async (file) => data<KolSamplesPreview>("/kol-samples/preview", { method: "POST", body: { file_b64: await fileToBase64(file) } }),
    apply: async (file, reason, fileHash) => data<KolSamplesApplied>("/kol-samples/apply", { method: "POST", body: { file_b64: await fileToBase64(file), reason, file_hash: fileHash } }),
  };
}
