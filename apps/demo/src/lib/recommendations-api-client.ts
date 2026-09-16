import type { DemoDecisionItem, DemoDecisionListResponse } from "@juli/contracts";

/**
 * Signed-in Decisions read route (#1320, ADR-094). `/v1/demo/recommendations`
 * never existed as a backend route — this now mirrors the server-side route
 * actually mounted: `APIRouter(prefix="/demo/decisions")` in
 * `backend/src/juli_backend/api/routes/demo_decisions.py`, included under
 * `v1_router = APIRouter(prefix="/v1")` in `api/app.py`. Per ADR-094 this is
 * the signed-in path only — the anonymous replay entry issues no `/v1/*`
 * request at all (#1319).
 *
 * Split out of `lib/recommendations.ts` (issue #1772): that file's pure,
 * network-free fixtures and href builders are imported by the review page,
 * which the anonymous replay door reaches. Keeping the literal `/v1/*` path
 * constants and the fetch clients that use them in a separate module means
 * `replay-module-graph.test.ts`'s walk of the review page's entry never
 * resolves into a module that performs a fetch to a Juli backend route —
 * this file is imported by nothing on the replay path, only by its own
 * test today (ADR-094's #1353-style "producer with no caller yet").
 */
export const DEMO_DECISIONS_API_PATH = "/v1/demo/decisions" as const;

export class DemoRecommendationsFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Demo recommendations fetch failed (${status})`);
    this.name = "DemoRecommendationsFetchError";
  }
}

interface SignedInRequestOptions {
  /** The seller's real Supabase bearer token — required; there is no
   *  unauthenticated read of this route (ADR-075 decision 3, #1283). */
  token: string;
  /** The acting shop (`lib/shop-session.ts`) — `get_active_shop` ownership-
   *  checks it server-side; requests without it are rejected. */
  shopId: string;
  fetchImpl?: typeof fetch;
}

/**
 * Signed-in recommendations read (#1320 → wired in by #1909, ADR-094).
 * Parses the route's REAL envelope (`DemoDecisionListResponse`,
 * `packages/contracts/src/decisions.ts` — `{ success, data, error }`, never
 * a `recommendations` key) and authenticates the way the backend actually
 * demands: bearer token + `X-Shop-Id`, the same pair every other
 * authenticated `/v1/*` route uses. A failed fetch, a non-OK response, or
 * a malformed 200 payload all reject rather than resolving to
 * `recommendationFixtures`. A dead or unreachable backend must surface as
 * a failure a caller can render honestly, never as fixture content
 * standing in for it.
 */
export async function fetchRecommendations(
  options: SignedInRequestOptions,
): Promise<readonly DemoDecisionItem[]> {
  const { token, shopId, fetchImpl = fetch } = options;

  const response = await fetchImpl(DEMO_DECISIONS_API_PATH, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "X-Shop-Id": shopId,
    },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new DemoRecommendationsFetchError(response.status);
  }

  const payload = (await response.json()) as Partial<DemoDecisionListResponse>;

  if (!Array.isArray(payload.data)) {
    throw new DemoRecommendationsFetchError(response.status);
  }

  return payload.data;
}

export class DemoDecisionApproveError extends Error {
  constructor(public readonly status: number) {
    super(`Demo decision approve failed (${status})`);
    this.name = "DemoDecisionApproveError";
  }
}

/**
 * Approve-is-run-creation, from the browser (#1909, ADR-075 decision 1).
 * `POST /v1/demo/decisions/{action_card_id}/approve`
 * (`backend/src/juli_backend/api/routes/demo_execution.py`) — a 202 whose
 * body carries the created `workflow_runs` row's own `run_id`. The caller
 * navigates with THAT id and nothing else: a 202 without one is an error,
 * never a license to construct an id client-side. 401 (session no longer
 * valid), 404 (unknown or cross-tenant card — the server never
 * distinguishes), 409 (already decided / no product to bind / concurrent
 * run) and 429 all reject with the status preserved so the caller can
 * render the honest, distinct condition.
 */
export async function approveDemoDecision(
  actionCardId: string,
  options: SignedInRequestOptions,
): Promise<{ runId: string }> {
  const { token, shopId, fetchImpl = fetch } = options;

  const response = await fetchImpl(
    `${DEMO_DECISIONS_API_PATH}/${encodeURIComponent(actionCardId)}/approve`,
    {
      method: "POST",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        "X-Shop-Id": shopId,
      },
    },
  );

  if (!response.ok) {
    throw new DemoDecisionApproveError(response.status);
  }

  let runId: unknown;
  try {
    const payload = (await response.json()) as {
      data?: { run_id?: unknown } | null;
    };
    runId = payload.data?.run_id;
  } catch {
    runId = undefined;
  }

  if (typeof runId !== "string" || runId.length === 0) {
    throw new DemoDecisionApproveError(response.status);
  }

  return { runId };
}

