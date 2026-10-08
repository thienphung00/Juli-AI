import type { HeroRanking, ShopAnalysisEnvelope } from "./types";

/**
 * Signed-in Phân tích read (AC-7.7, D21): the latest ADR-108 shop diagnosis
 * report for the acting shop. Authenticates exactly like
 * `lib/recommendations-api-client.ts` — bearer token + `X-Shop-Id` — and is
 * imported only by the signed-in Phân tích branch, never by the anonymous
 * sample (which issues no request at all).
 *
 * 404 means "no report built for this shop yet" and resolves to `null` so
 * the caller can render an honest empty state; every other failure rejects
 * and is never papered over with the synthetic sample.
 */
export const DEMO_ANALYSIS_API_PATH = "/v1/demo/analysis" as const;

export class ShopAnalysisFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Shop analysis fetch failed (${status})`);
    this.name = "ShopAnalysisFetchError";
  }
}

interface SignedInRequestOptions {
  token: string;
  shopId: string;
  /** Hero ranking; omitted → the server default ("60d"). */
  ranking?: HeroRanking;
  fetchImpl?: typeof fetch;
}

function isEnvelope(value: unknown): value is ShopAnalysisEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const report = (value as { report?: unknown }).report;
  return (
    typeof report === "object" &&
    report !== null &&
    Array.isArray((report as { channels?: unknown }).channels) &&
    typeof (report as { windows?: unknown }).windows === "object"
  );
}

export async function fetchShopAnalysis(
  options: SignedInRequestOptions,
): Promise<ShopAnalysisEnvelope | null> {
  const { token, shopId, ranking, fetchImpl = fetch } = options;
  const url = ranking
    ? `${DEMO_ANALYSIS_API_PATH}?ranking=${encodeURIComponent(ranking)}`
    : DEMO_ANALYSIS_API_PATH;

  const response = await fetchImpl(url, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "X-Shop-Id": shopId,
    },
    cache: "no-store",
  });

  if (response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new ShopAnalysisFetchError(response.status);
  }

  const payload: unknown = await response.json();
  // Tolerate the `{ success, data, error }` envelope other demo routes use.
  const body =
    typeof payload === "object" && payload !== null && "data" in payload
      ? (payload as { data: unknown }).data
      : payload;

  if (!isEnvelope(body)) {
    throw new ShopAnalysisFetchError(response.status);
  }

  return body;
}
