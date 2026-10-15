/**
 * The partner trial account's two backend calls (fast track P32-A, contract
 * `fasttrack/contracts/p32-reviewer-access.md` §4 and §6):
 *
 * - `GET /v1/reviewer/me` — is this session a reviewer, which platform, until
 *   when, which (aliased) shop;
 * - `POST /v1/reviewer/decisions/{id}/simulate` — Duyệt / Thực thi as a
 *   simulation: the change Juli would send, nothing sent.
 *
 * A denied reviewer gets 403 with `X-Juli-Reviewer-Denied` (expired, revoked,
 * unknown, read_only, unavailable) or 503 (unconfigured).
 */

export type ReviewerDenial = "expired" | "revoked" | "unknown" | "read_only" | "unavailable" | "unconfigured";

export interface ReviewerMe {
  readonly reviewer: true;
  readonly platform: string;
  readonly expiresAt: string | null;
  readonly shop: { readonly id: string; readonly name: string };
}

export type ReviewerMeResult =
  | { status: "reviewer"; me: ReviewerMe }
  | { status: "not_reviewer" }
  | { status: "denied"; denial: ReviewerDenial }
  | { status: "error" };

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

const DENIALS: ReadonlySet<string> = new Set(["expired", "revoked", "unknown", "read_only", "unavailable", "unconfigured"]);

export function reviewerDenialOf(response: Response): ReviewerDenial | null {
  const header = response.headers.get("X-Juli-Reviewer-Denied");
  if (header && DENIALS.has(header)) return header as ReviewerDenial;
  if (response.status === 503) return "unconfigured";
  return null;
}

export async function fetchReviewerMe(token: string, fetchImpl: FetchLike = (i, init) => fetch(i, init)): Promise<ReviewerMeResult> {
  let response: Response;
  try {
    response = await fetchImpl("/v1/reviewer/me", {
      headers: { Accept: "application/json", Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return { status: "error" };
  }
  if (!response.ok) {
    const denial = reviewerDenialOf(response);
    return denial ? { status: "denied", denial } : { status: "error" };
  }
  let body: Record<string, unknown> | null = null;
  try {
    body = (await response.json()) as Record<string, unknown>;
  } catch {
    return { status: "error" };
  }
  if (body?.reviewer !== true) return { status: "not_reviewer" };
  const shop = body.shop as { id?: unknown; name?: unknown } | undefined;
  if (!shop || typeof shop.id !== "string" || !shop.id) return { status: "error" };
  return {
    status: "reviewer",
    me: {
      reviewer: true,
      platform: typeof body.platform === "string" ? body.platform : "",
      expiresAt: typeof body.expires_at === "string" ? body.expires_at : null,
      shop: { id: shop.id, name: typeof shop.name === "string" ? shop.name : "" },
    },
  };
}

export type SimulationStep = "approve" | "execute";

export interface SimulatedField {
  readonly field: string;
  readonly label: string;
  readonly before: string | null;
  readonly after: string | null;
}

export interface SimulatedRequest {
  readonly method: string;
  readonly path: string;
  readonly operation: string;
  readonly fields: readonly string[];
}

export interface SimulationResult {
  readonly simulated: true;
  readonly step: SimulationStep;
  readonly action_card_id: string;
  readonly label: string;
  readonly steps: readonly { readonly key: string; readonly label: string; readonly done: boolean }[];
  readonly change: {
    readonly executor: string;
    readonly lever: { readonly code: string; readonly label: string };
    readonly product: { readonly title: string | null; readonly tiktok_product_id: string | null };
    readonly request: SimulatedRequest | null;
    readonly fields: readonly SimulatedField[];
    readonly note: string | null;
  };
  readonly enqueued: false;
  readonly tiktok_write: false;
}

export class ReviewerSimulationError extends Error {
  constructor(
    readonly status: number,
    readonly denial: ReviewerDenial | null,
  ) {
    super(`reviewer simulation failed (${status})`);
  }
}

export async function simulateDecision(
  actionCardId: string,
  step: SimulationStep,
  options: { token: string; shopId: string; fetchImpl?: FetchLike },
): Promise<SimulationResult> {
  const fetchImpl = options.fetchImpl ?? ((i, init) => fetch(i, init));
  let response: Response;
  try {
    response = await fetchImpl(`/v1/reviewer/decisions/${encodeURIComponent(actionCardId)}/simulate`, {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        Authorization: `Bearer ${options.token}`,
        "X-Shop-Id": options.shopId,
      },
      cache: "no-store",
      body: JSON.stringify({ step }),
    });
  } catch {
    throw new ReviewerSimulationError(0, null);
  }
  if (!response.ok) throw new ReviewerSimulationError(response.status, reviewerDenialOf(response));
  const body = (await response.json()) as SimulationResult;
  if (body?.simulated !== true) throw new ReviewerSimulationError(response.status, null);
  return body;
}
