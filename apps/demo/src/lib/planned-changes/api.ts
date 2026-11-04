import { ShopInputsError, fileToBase64 } from "../shop-inputs/api";
import type { PlannedApplied, PlannedChangesApi, PlannedImport, PlannedOverview, PlannedPreview, TemplateFile } from "./types";

/** `/v1/demo/shop-inputs/planned-changes` (seller) or `/v1/ops/shops/{id}/planned-changes` (Ops). */
export const DEMO_PLANNED_BASE = "/v1/demo/shop-inputs/planned-changes" as const;

export function opsPlannedBase(shopId: string): string {
  return `/v1/ops/shops/${encodeURIComponent(shopId)}/planned-changes`;
}

export interface PlannedClientOptions {
  readonly base: string;
  readonly token: string;
  /** The seller API names the shop in a header; the Ops API in the path. */
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

async function failure(response: Response): Promise<ShopInputsError> {
  let code: string | null = null;
  let message = "Không thực hiện được. Bạn thử lại sau ít phút nhé.";
  try {
    const detail = ((await response.json()) as { detail?: unknown }).detail;
    if (typeof detail === "string") message = detail;
    else if (detail && typeof detail === "object") {
      const d = detail as { code?: unknown; message?: unknown };
      if (typeof d.code === "string") code = d.code;
      if (typeof d.message === "string") message = d.message;
    }
  } catch {
    // non-JSON error body: keep the generic sentence
  }
  return new ShopInputsError(response.status, code, message);
}

export function createPlannedChangesApi(options: PlannedClientOptions): PlannedChangesApi {
  const fetchImpl = options.fetchImpl ?? fetch;
  const call = async (path: string, init: { method?: string; body?: unknown } = {}): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json", Authorization: `Bearer ${options.token}` };
    if (options.shopId) headers["X-Shop-Id"] = options.shopId;
    if (init.body !== undefined) headers["Content-Type"] = "application/json";
    const response = await fetchImpl(`${options.base}${path}`, {
      method: init.method ?? "GET",
      headers,
      cache: "no-store",
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
    });
    if (!response.ok) throw await failure(response);
    return response;
  };
  const data = async <T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> =>
    ((await (await call(path, init)).json()) as { data: T }).data;
  return {
    overview: () => data<PlannedOverview>(""),
    template: async (): Promise<TemplateFile> => {
      const response = await call("/template");
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const filename = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "de-xuat-ke-hoach-mau.xlsx";
      return { blob: await response.blob(), filename };
    },
    preview: async (file) => data<PlannedPreview>("/preview", { method: "POST", body: { file_b64: await fileToBase64(file) } }),
    apply: async (file, reason, fileHash) =>
      data<PlannedApplied>("/apply", { method: "POST", body: { file_b64: await fileToBase64(file), reason, file_hash: fileHash } }),
    versions: async () => (await data<{ imports: PlannedImport[] }>("/versions")).imports,
    version: (number) => data<PlannedImport>(`/versions/${number}`),
  };
}
