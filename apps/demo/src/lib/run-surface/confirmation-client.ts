/**
 * Fetch client for `POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}`
 * (issue #1317, ADR-075 decision 2 / PUI-DESIGN.md §3) -- the consent-grade
 * option picker's ONLY write path.
 *
 * Same-origin relative base path, matching `agent-event-stream.ts`'s
 * `AGENT_EVENT_STREAM_DEFAULT_BASE_URL` convention (demo workspace contract
 * #397: no client env API base). Bearer auth in a header, never the URL --
 * same rationale as the SSE transport (logs/history/referrer never see it).
 *
 * The body carries exactly what the security-sensitive acceptance criteria
 * name: the run's `tool_call_id` (in the URL, same as the confirmation the
 * event named) and the SELECTED option's `option_id` (approve only; decline
 * carries none). Nothing else. This module knows nothing about which option
 * was displayed or dimmed -- it only ever sends the id the caller passes in,
 * so "selecting A then B then confirming sends B" is a property of the
 * CALLER holding one piece of state (`selectedOptionId`), not of anything
 * this client does.
 *
 * Errors from the backend's confirmation ladder
 * (`services/agent_runs/confirmations.py`) carry a distinct, stable
 * `error_code` string in `detail.error_code` -- `ConfirmationRejectedError`
 * below preserves it so a caller can render the honest, distinct condition
 * (fingerprint mismatch, already-decided, not-awaiting, expired, ...)
 * rather than a generic failure. A malformed or non-JSON error body (rate
 * limit's plain-string `detail`, a network-layer 5xx) still raises with a
 * `null` `errorCode` -- callers branch on that too.
 */

export const CONFIRMATION_API_DEFAULT_BASE_URL = "/v1/demo" as const;

export type ConfirmationDecisionKind = "approve" | "decline";

export interface SubmitConfirmationDecisionOptions {
  readonly token?: string;
  readonly baseUrl?: string;
  readonly fetchImpl?: typeof fetch;
}

export interface ConfirmationDecisionResult {
  readonly decision: ConfirmationDecisionKind;
  readonly status: string;
  readonly celeryTaskId: string;
}

/** Mirrors `services/agent_runs/confirmations.py`'s `ERROR_*` constants --
 *  transcribed, not re-derived, so a code this client does not recognize
 *  still carries its raw string through rather than being coerced into a
 *  known one. */
export type ConfirmationErrorCode =
  | "run_not_awaiting_confirmation"
  | "confirmation_not_found"
  | "confirmation_already_decided"
  | "confirmation_expired"
  | "invalid_decision"
  | "option_id_required"
  | "unknown_option_id"
  | "params_sha_mismatch"
  | "run_state_not_reconstructable"
  | (string & {});

export class ConfirmationRejectedError extends Error {
  constructor(
    public readonly status: number,
    public readonly errorCode: ConfirmationErrorCode | null,
    message: string,
  ) {
    super(message);
    this.name = "ConfirmationRejectedError";
  }
}

export function buildConfirmationDecisionUrl(
  runId: string,
  toolCallId: string,
  baseUrl: string = CONFIRMATION_API_DEFAULT_BASE_URL,
): string {
  return `${baseUrl}/runs/${encodeURIComponent(runId)}/confirmations/${encodeURIComponent(toolCallId)}`;
}

interface RejectedBody {
  detail?: { message?: unknown; error_code?: unknown } | string;
}

async function rejectionFromResponse(response: Response): Promise<ConfirmationRejectedError> {
  let body: RejectedBody | null = null;
  try {
    body = (await response.json()) as RejectedBody;
  } catch {
    body = null;
  }

  const detail = body?.detail;
  if (detail && typeof detail === "object") {
    const message = typeof detail.message === "string" ? detail.message : response.statusText;
    const errorCode = typeof detail.error_code === "string" ? detail.error_code : null;
    return new ConfirmationRejectedError(response.status, errorCode, message);
  }
  if (typeof detail === "string") {
    return new ConfirmationRejectedError(response.status, null, detail);
  }
  return new ConfirmationRejectedError(
    response.status,
    null,
    `Confirmation decision failed (${response.status})`,
  );
}

/**
 * Submits a seller's decision on a paused confirmation.
 *
 * `decision: "approve"` requires `optionId` -- the server's own
 * `option_id_required` rejection is the backstop, but this client also
 * refuses locally rather than sending a request the server can only ever
 * reject, matching "no single interaction sends a confirmation" at the
 * boundary where a caller could otherwise construct one.
 */
export async function submitConfirmationDecision(
  runId: string,
  toolCallId: string,
  decision: ConfirmationDecisionKind,
  optionId: string | null,
  options: SubmitConfirmationDecisionOptions = {},
): Promise<ConfirmationDecisionResult> {
  const { token, baseUrl, fetchImpl = fetch } = options;

  if (decision === "approve" && !optionId) {
    throw new ConfirmationRejectedError(
      422,
      "option_id_required",
      "An approve decision requires option_id.",
    );
  }

  const headers = new Headers({ "Content-Type": "application/json", Accept: "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetchImpl(buildConfirmationDecisionUrl(runId, toolCallId, baseUrl), {
    method: "POST",
    headers,
    body: JSON.stringify({
      decision,
      option_id: decision === "approve" ? optionId : null,
    }),
  });

  if (!response.ok) {
    throw await rejectionFromResponse(response);
  }

  const body = (await response.json()) as {
    decision: ConfirmationDecisionKind;
    status: string;
    celery_task_id: string;
  };
  return { decision: body.decision, status: body.status, celeryTaskId: body.celery_task_id };
}
