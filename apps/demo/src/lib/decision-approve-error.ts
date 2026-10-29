/**
 * The approve route's failure, by status (#1909). Split out of
 * `recommendations-api-client.ts` so `quyet-dinh/approve-errors.ts` — which
 * the signed-out sample Quyết định also renders through — never imports a
 * module holding a fetch call site (ADR-094 d.1, `replay-module-graph.test.ts`).
 *
 * P66 (D13): it also carries the refusal's `detail` when the server sent one — the
 * reviewer caps' `code` (`create_product_daily_cap` / `create_promotion_daily_cap`), the
 * `cap`, and `retry_at` (when the cap frees up) — so the card can say why, and until when.
 */
export interface ApproveRefusalDetail {
  readonly code: string | null;
  readonly cap: number | null;
  /** ISO 8601 (UTC) moment the cap frees up. */
  readonly retryAt: string | null;
  /** The server's own sentence, when `detail` was a plain string. */
  readonly message: string | null;
}

export class DemoDecisionApproveError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: ApproveRefusalDetail | null = null,
  ) {
    super(`Decision approve failed (${status})`);
    this.name = "DemoDecisionApproveError";
  }
}

/** The approve refusal body's `detail`, read defensively (any shape → fields or null). */
export function approveRefusalDetail(body: unknown): ApproveRefusalDetail | null {
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string") return { code: null, cap: null, retryAt: null, message: detail };
  if (!detail || typeof detail !== "object") return null;
  const record = detail as Record<string, unknown>;
  return {
    code: typeof record.code === "string" ? record.code : null,
    cap: typeof record.cap === "number" ? record.cap : null,
    retryAt: typeof record.retry_at === "string" ? record.retry_at : null,
    message: typeof record.message === "string" ? record.message : null,
  };
}
