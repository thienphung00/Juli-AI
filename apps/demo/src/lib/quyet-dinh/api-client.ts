/**
 * Signed-in clients for Quyết định's P8-C reads and writes (AC-8.7):
 * the rule store, a run's before/after changes, "Hoàn tác" and the day-7
 * "Hoàn tác?" questions. Bearer token + `X-Shop-Id`, same-origin relative
 * paths (#397). Never imported by the anonymous path
 * (`replay-module-graph.test.ts`).
 */

import { QdApiError, photoChecksOf, type AuthedOptions } from "./client-types";
import type { Measurement, PhotoCheck, RunDetail, SellerInstructions } from "./p10-types";
import type { ReasonChoice } from "./reasons";
import type { RevertQuestion, RuleKey, RunChanges, SetBy, ShopRules } from "./types";

// The error class, the options shape and the pure helpers live in the
// network-free `client-types.ts` (the sample door imports them); re-exported
// here so every existing import keeps working.
export {
  QdApiError,
  describeRevertError,
  isExternalChange,
  photoChecksOf,
  type AuthedOptions,
} from "./client-types";

const BASE = "/v1/demo";

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
  return parse<T>(response);
}

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let code: string | null = null;
    let message: string | null = null;
    let raw: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      raw = body;
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
    throw new QdApiError(response.status, code, message, raw);
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

/**
 * 202 → the new revert run's id; 409 / 503 / 429 reject with `QdApiError`.
 * P10 contract §2: the body carries exactly one `reason_code` (+ optional note).
 */
export async function startRunRevert(
  options: AuthedOptions,
  runId: string,
  reason?: ReasonChoice,
): Promise<{ runId: string }> {
  const body = await call<{ data?: { run_id?: unknown }; run_id?: unknown }>(
    `/runs/${encodeURIComponent(runId)}/revert`,
    options,
    { method: "POST", body: reason ? reasonBody(reason) : undefined },
  );
  const id = body.data?.run_id ?? body.run_id;
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

function reasonBody(reason: ReasonChoice): { reason_code: string; note?: string } {
  const note = reason.note?.trim();
  return note ? { reason_code: reason.reason_code, note } : { reason_code: reason.reason_code };
}

function unwrap<T>(body: unknown): T {
  if (body && typeof body === "object" && "data" in body && (body as { data: unknown }).data !== undefined) {
    return (body as { data: T }).data;
  }
  return body as T;
}

/** Contract §2: Từ chối a card → `{status:"rejected", cooldown_until}`. */
export async function rejectDecision(
  options: AuthedOptions,
  decisionId: string,
  reason: ReasonChoice,
): Promise<{ status: string; cooldown_until: string | null }> {
  const body = await call<unknown>(`/decisions/${encodeURIComponent(decisionId)}/reject`, options, {
    method: "POST",
    body: reasonBody(reason),
  });
  return unwrap(body);
}

/** Contract §2: Không thực hiện at the consent / seller-action step → `{status:"declined", cooldown_until}`. */
export async function declineRun(
  options: AuthedOptions,
  runId: string,
  reason: ReasonChoice,
): Promise<{ status: string; cooldown_until: string | null }> {
  const body = await call<unknown>(`/runs/${encodeURIComponent(runId)}/decline`, options, {
    method: "POST",
    body: reasonBody(reason),
  });
  return unwrap(body);
}

/** Contract §4: multipart `file` (JPG/PNG ≤ 5 MB) → 202 `{checks}`; failing checks → 422 with the same list. */
export async function uploadRunPhoto(options: AuthedOptions, runId: string, file: File): Promise<PhotoCheck[]> {
  const { token, shopId, fetchImpl = fetch } = options;
  const form = new FormData();
  form.append("file", file);
  const response = await fetchImpl(`${BASE}/runs/${encodeURIComponent(runId)}/photo`, {
    method: "POST",
    headers: { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopId },
    cache: "no-store",
    body: form,
  });
  const body = await parse<unknown>(response);
  return photoChecksOf(body) ?? [];
}

/** `GET /v1/demo/runs/{id}` (P10-B): `awaiting`, the cover-photo URLs/checks, the promotion. */
export async function fetchRunDetail(options: AuthedOptions, runId: string): Promise<RunDetail> {
  return unwrap(await call<unknown>(`/runs/${encodeURIComponent(runId)}`, options));
}

/** Contract §5. */
export async function fetchRunInstructions(options: AuthedOptions, runId: string): Promise<SellerInstructions> {
  return unwrap(await call<unknown>(`/runs/${encodeURIComponent(runId)}/instructions`, options));
}

/** Contract §5: "Tôi đã áp dụng" → 202; Juli then verifies on TikTok. */
export async function markRunApplied(options: AuthedOptions, runId: string): Promise<void> {
  await call(`/runs/${encodeURIComponent(runId)}/applied`, options, { method: "POST" });
}

/** Contract §6; `null` while the endpoint is not deployed (404). */
export async function fetchRunMeasurement(options: AuthedOptions, runId: string): Promise<Measurement | null> {
  try {
    return unwrap(await call<unknown>(`/runs/${encodeURIComponent(runId)}/measurement`, options));
  } catch (error) {
    if (error instanceof QdApiError && error.status === 404) return null;
    throw error;
  }
}
