import type {
  ApplyResult,
  ImportPreview,
  InputsOverview,
  RestoreResult,
  ShopInputsApi,
  SkuVersions,
  TemplateFile,
  VersionSku,
} from "./types";

/** A non-2xx answer; `message` is the backend's Vietnamese sentence when it sent one. */
export class ShopInputsError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    message: string,
  ) {
    super(message);
    this.name = "ShopInputsError";
  }
}

export interface ShopInputsClientOptions {
  /** `/v1/demo/shop-inputs` or `/v1/ops/shops/{id}/inputs`. */
  readonly base: string;
  readonly token: string;
  /** The seller API names the shop in a header; the Ops API in the path. */
  readonly shopId?: string;
  readonly fetchImpl?: typeof fetch;
}

/** Base64 of a file (the API takes the workbook inside JSON, no multipart). */
export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Không đọc được tệp"));
    reader.onload = () => {
      const url = String(reader.result ?? "");
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.readAsDataURL(file);
  });
}

async function failure(response: Response): Promise<ShopInputsError> {
  let code: string | null = null;
  let message = "Không thực hiện được. Bạn thử lại sau ít phút nhé.";
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
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

export function createShopInputsApi(options: ShopInputsClientOptions): ShopInputsApi {
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
    overview: () => data<InputsOverview>(""),
    template: async (): Promise<TemplateFile> => {
      const response = await call("/template");
      const disposition = response.headers.get("Content-Disposition") ?? "";
      const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? "thong-so-mau.xlsx";
      return { blob: await response.blob(), filename: name, skuRows: Number(response.headers.get("X-Sku-Rows") ?? 0) };
    },
    preview: async (file) => data<ImportPreview>("/preview", { method: "POST", body: { file_b64: await fileToBase64(file) } }),
    apply: async (file, reason, fileHash) =>
      data<ApplyResult>("/apply", {
        method: "POST",
        body: { file_b64: await fileToBase64(file), reason, file_hash: fileHash },
      }),
    versionsIndex: async () => (await data<{ skus: VersionSku[] }>("/versions")).skus,
    versions: (scopeRef) => data<SkuVersions>(`/versions?scope_ref=${encodeURIComponent(scopeRef)}`),
    restore: (scopeRef, version) =>
      data<RestoreResult>("/restore", { method: "POST", body: { scope_ref: scopeRef, version } }),
  };
}

/** Browser download of a generated file; a no-op where object URLs do not exist. */
export function saveBlob(file: Blob, filename: string): void {
  if (typeof URL === "undefined" || typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(file);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
