/**
 * The partner reviewer's live TikTok sandbox calls (fast track P64, D73;
 * backend `api/routes/reviewer.py`): the shop + its TikTok connection and "Đồng
 * bộ ngay". Duyệt is the seller's own approve (D73.4): an agent run, streamed
 * over SSE like any seller run (`lib/recommendations-api-client`).
 */

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface SandboxOptions {
  readonly token: string;
  readonly shopId?: string;
  readonly fetchImpl?: FetchLike;
}

export interface SandboxShop {
  readonly shop: { readonly id: string; readonly name: string; readonly tiktok_shop_id: string | null; readonly platform: string };
  readonly mode: string;
  readonly writes_enabled: boolean;
  readonly connection: {
    readonly status: string;
    readonly capability?: string | null;
    readonly authorized_at: string | null;
    readonly last_refreshed_at: string | null;
    readonly token_expires_at: string | null;
    readonly scopes: readonly string[];
  };
  readonly synced_at: string | null;
  readonly sync_endpoints: readonly string[];
  readonly sync_interval_seconds: number;
}

export type SyncResult =
  | { readonly status: "queued"; readonly syncedAt: string | null; readonly retryAfterSeconds: number }
  | { readonly status: "rate_limited"; readonly retryAfterSeconds: number }
  | { readonly status: "unavailable" }
  | { readonly status: "error" };

export class SandboxError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | null,
    readonly tiktokCode: number | null = null,
  ) {
    super(`reviewer sandbox call failed (${status}${code ? ` ${code}` : ""})`);
  }
}

function headers(options: SandboxOptions, json = false): Record<string, string> {
  return {
    Accept: "application/json",
    ...(json ? { "Content-Type": "application/json" } : {}),
    Authorization: `Bearer ${options.token}`,
    ...(options.shopId ? { "X-Shop-Id": options.shopId } : {}),
  };
}

function call(options: SandboxOptions, path: string, init: RequestInit): Promise<Response> {
  const fetchImpl = options.fetchImpl ?? ((i, o) => fetch(i, o));
  return fetchImpl(path, { ...init, cache: "no-store" });
}

async function detailOf(response: Response): Promise<{ code: string | null; tiktokCode: number | null; retryAfter: number | null }> {
  try {
    const body = (await response.json()) as { detail?: { code?: unknown; tiktok_code?: unknown; retry_after_seconds?: unknown } | string };
    const detail = typeof body?.detail === "object" && body.detail ? body.detail : {};
    return {
      code: typeof detail.code === "string" ? detail.code : null,
      tiktokCode: typeof detail.tiktok_code === "number" ? detail.tiktok_code : null,
      retryAfter: typeof detail.retry_after_seconds === "number" ? detail.retry_after_seconds : null,
    };
  } catch {
    return { code: null, tiktokCode: null, retryAfter: null };
  }
}

async function failure(response: Response): Promise<SandboxError> {
  const { code, tiktokCode } = await detailOf(response);
  return new SandboxError(response.status, code, tiktokCode);
}

export async function fetchSandboxShop(options: SandboxOptions): Promise<SandboxShop> {
  let response: Response;
  try {
    response = await call(options, "/v1/reviewer/shop", { headers: headers(options) });
  } catch {
    throw new SandboxError(0, null);
  }
  if (!response.ok) throw await failure(response);
  return (await response.json()) as SandboxShop;
}

export async function syncSandboxShop(options: SandboxOptions): Promise<SyncResult> {
  let response: Response;
  try {
    response = await call(options, "/v1/reviewer/shop/sync", { method: "POST", headers: headers(options) });
  } catch {
    return { status: "error" };
  }
  if (response.status === 429) {
    const { retryAfter } = await detailOf(response);
    const header = Number(response.headers.get("Retry-After"));
    return { status: "rate_limited", retryAfterSeconds: retryAfter ?? (Number.isFinite(header) && header > 0 ? header : 60) };
  }
  if (response.status === 503) return { status: "unavailable" };
  if (!response.ok) return { status: "error" };
  const body = (await response.json()) as { synced_at?: string | null; retry_after_seconds?: number };
  return { status: "queued", syncedAt: body.synced_at ?? null, retryAfterSeconds: body.retry_after_seconds ?? 60 };
}
