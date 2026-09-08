import type { RecommendationFixture } from "./recommendations";

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
export const ACTION_CARD_INPUTS_API_PATH = "/v1/action-cards" as const;

export class DemoRecommendationsFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Demo recommendations fetch failed (${status})`);
    this.name = "DemoRecommendationsFetchError";
  }
}

export interface ActionCardInputsData {
  workflow_key: string;
  sku_id: string | null;
  tiktok_product_id: string | null;
  current_stock: number | null;
  reorder_quantity: number | null;
  editable: boolean;
  basis: {
    daily_velocity: number;
    lead_time_days: number;
    safety_stock_days: number;
    days_until_stockout: number;
  } | null;
}

export class ActionCardInputsFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Action card inputs fetch failed (${status})`);
    this.name = "ActionCardInputsFetchError";
  }
}

/**
 * Signed-in recommendations read (#1320, ADR-094 — partial delivery, see
 * `apps/demo/MODULE.md`). A failed fetch, a non-OK response, or a malformed
 * 200 payload all reject rather than resolving to `recommendationFixtures`.
 * A dead or unreachable backend must surface as a failure a caller can
 * render honestly, never as fixture content standing in for it. Not yet
 * called from `RecommendationsPanel` — see MODULE.md for why.
 */
export async function fetchRecommendations(
  fetchImpl: typeof fetch = fetch,
): Promise<readonly RecommendationFixture[]> {
  const response = await fetchImpl(DEMO_DECISIONS_API_PATH, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new DemoRecommendationsFetchError(response.status);
  }

  const payload = (await response.json()) as {
    recommendations?: RecommendationFixture[];
  };

  if (!Array.isArray(payload.recommendations)) {
    throw new DemoRecommendationsFetchError(response.status);
  }

  return payload.recommendations;
}

export async function fetchActionCardInputs(
  workflowKey: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ActionCardInputsData | null> {
  try {
    const response = await fetchImpl(
      `${ACTION_CARD_INPUTS_API_PATH}/${workflowKey}/inputs`,
      {
        headers: { Accept: "application/json" },
        cache: "no-store",
      },
    );

    if (!response.ok) {
      throw new ActionCardInputsFetchError(response.status);
    }

    const payload = (await response.json()) as {
      success?: boolean;
      data?: ActionCardInputsData;
    };

    if (payload.data) {
      return payload.data;
    }
  } catch {
    // Fallback to fixture when backend unavailable — demo remains functional offline.
  }

  return null;
}
