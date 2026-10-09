/**
 * Signed-in clients for Quyết định's P8-C reads and writes (AC-8.7):
 * the rule store, a run's before/after changes, "Hoàn tác" and the day-7
 * "Hoàn tác?" questions. Bearer token + `X-Shop-Id`, same-origin relative
 * paths (#397). Never imported by the anonymous path
 * (`replay-module-graph.test.ts`).
 */

import type { RevertQuestion, RuleKey, RunChanges, SetBy, ShopRules } from "./types";

const BASE = "/v1/demo";

export interface AuthedOptions {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}

/** A non-2xx answer. `message` is the backend's Vietnamese sentence when it sent one. */
export class QdApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string | null,
    public readonly serverMessage: string | null,
  ) {
    super(serverMessage ?? `Request failed (${status})`);
    this.name = "QdApiError";
  }
}

async function call<T>(
  path: string,
  { token, shopId, fetchImpl = fetch }: AuthedOptions,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    Accept: "application/json",
    Authorization: `Bearer ${token}`,
    "X-Shop-Id": shopId,
  };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetchImpl(`${BASE}${path}`, {
    method: init.method ?? "GET",
    headers,
    cache: "no-store",
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!response.ok) {
    let code: string | null = null;
    let message: string | null = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      const detail = body.detail;
      if (detail && typeof detail === "object") {
        const d = detail as { code?: unknown; message?: unknown };
        code = typeof d.code === "string" ? d.code : null;
        message = typeof d.message === "string" ? d.message : null;
      } else if (typeof detail === "string") {
        message = detail;
      }
    } catch {
      // non-JSON error body: status only
    }
    throw new QdApiError(response.status, code, message);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function fetchShopRules(options: AuthedOptions): Promise<ShopRules> {
  const body = await call<{ data: ShopRules }>("/rules", options);
  return body.data;
}

export async function putShopRule(
  options: AuthedOptions,
  ruleKey: RuleKey,
  value: unknown,
  setBy: SetBy,
  scopeRef: string | null = null,
): Promise<void> {
  await call(`/rules/${encodeURIComponent(ruleKey)}`, options, {
    method: "PUT",
    body: { scope_ref: scopeRef, value, set_by: setBy },
  });
}

export async function deleteShopRule(
  options: AuthedOptions,
  ruleKey: RuleKey,
  scopeRef: string | null = null,
): Promise<void> {
  const query = scopeRef ? `?scope_ref=${encodeURIComponent(scopeRef)}` : "";
  await call(`/rules/${encodeURIComponent(ruleKey)}${query}`, options, { method: "DELETE" });
}

export async function fetchRunChanges(options: AuthedOptions, runId: string): Promise<RunChanges> {
  return call<RunChanges>(`/runs/${encodeURIComponent(runId)}/changes`, options);
}

/** 202 → the new revert run's id; 409 / 503 / 429 reject with `QdApiError`. */
export async function startRunRevert(options: AuthedOptions, runId: string): Promise<{ runId: string }> {
  const body = await call<{ data?: { run_id?: unknown } }>(
    `/runs/${encodeURIComponent(runId)}/revert`,
    options,
    { method: "POST" },
  );
  const id = body.data?.run_id;
  if (typeof id !== "string" || !id) throw new QdApiError(202, null, null);
  return { runId: id };
}

export async function fetchRevertQuestions(options: AuthedOptions): Promise<RevertQuestion[]> {
  const body = await call<{ data: RevertQuestion[] }>("/revert-questions", options);
  return body.data;
}

export async function dismissRevertQuestion(options: AuthedOptions, questionId: string): Promise<void> {
  await call(`/revert-questions/${encodeURIComponent(questionId)}/dismiss`, options, { method: "POST" });
}

/** Seller-facing sentence for a failed revert: the backend's own words when given. */
export function describeRevertError(error: unknown): string {
  if (error instanceof QdApiError) {
    if (error.serverMessage && (error.status === 409 || error.status === 503)) return error.serverMessage;
    if (error.status === 429) return "Bạn vừa gửi quá nhiều yêu cầu. Vui lòng thử lại sau ít phút.";
    if (error.status === 404) return "Không tìm thấy lượt chạy này trong shop bạn đang thao tác.";
    if (error.status === 401) return "Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập lại.";
    return `Chưa thể hoàn tác lúc này (lỗi ${error.status}). Vui lòng thử lại.`;
  }
  return "Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.";
}
