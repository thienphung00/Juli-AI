/**
 * The partner trial account's two backend calls (fast track P32-A, contract
 * `fasttrack/contracts/p32-reviewer-access.md` §4 and §6):
 *
 * - `GET /v1/reviewer/me` — is this session a reviewer, which platform, until
 *   when, which (aliased) shop — or `shop: null` when none is pinned (P32-D,
 *   D42 amendment: the reviewer then sees the bundled sample shop);
 * - `POST /v1/reviewer/decisions/{id}/simulate` — Duyệt / Thực thi as a
 *   simulation: the change Juli would send, nothing sent.
 *
 * A denied reviewer gets 403 with `X-Juli-Reviewer-Denied` (expired, revoked,
 * unknown, read_only, unavailable) or 503 (unconfigured).
 */

import { parseReviewerShops, type ReviewerShopOption } from "./session";
import type { SimulationResult, SimulationStep } from "./simulation-types";

export type ReviewerDenial = "expired" | "revoked" | "unknown" | "read_only" | "unavailable" | "unconfigured";

export interface ReviewerMe {
  readonly reviewer: true;
  readonly platform: string;
  readonly expiresAt: string | null;
  /** null: no pinned shop — sample mode (P32-D). */
  readonly shop: { readonly id: string; readonly name: string } | null;
  /** P64 (D73): "sandbox" (live, unmasked) | "masked" | null. */
  readonly mode?: "sandbox" | "masked";
  readonly writesEnabled?: boolean;
  /** P74-A (D77): every pinned shop, default first (empty with no pin). */
  readonly shops?: readonly ReviewerShopOption[];
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

/**
 * `shopId` (P74-A, D77): the active shop, sent as `X-Shop-Id` so `shop` / `mode`
 * describe the pin the reviewer switched to. A value that names no pin answers
 * the default pin (the first), never an error.
 */
export async function fetchReviewerMe(
  token: string,
  fetchImpl: FetchLike = (i, init) => fetch(i, init),
  shopId?: string | null,
): Promise<ReviewerMeResult> {
  let response: Response;
  try {
    response = await fetchImpl("/v1/reviewer/me", {
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(shopId ? { "X-Shop-Id": shopId } : {}),
      },
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
  const shop = body.shop as { id?: unknown; name?: unknown } | null | undefined;
  if (shop !== null && (!shop || typeof shop.id !== "string" || !shop.id)) return { status: "error" };
  return {
    status: "reviewer",
    me: {
      reviewer: true,
      platform: typeof body.platform === "string" ? body.platform : "",
      expiresAt: typeof body.expires_at === "string" ? body.expires_at : null,
      shop: shop === null ? null : { id: shop.id as string, name: typeof shop.name === "string" ? shop.name : "" },
      ...(body.mode === "sandbox" || body.mode === "masked" ? { mode: body.mode } : {}),
      ...(body.writes_enabled === true ? { writesEnabled: true } : {}),
      ...(parseReviewerShops(body.shops).length > 0 ? { shops: parseReviewerShops(body.shops) } : {}),
    },
  };
}

export { parseReviewerShops, type ReviewerShopOption } from "./session";
export type { SimulatedField, SimulatedRequest, SimulationResult, SimulationStep } from "./simulation-types";

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
