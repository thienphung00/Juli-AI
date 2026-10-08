import type { RankedMetric, RankedStream, RankingEnvelope } from "./types";

/**
 * Signed-in read of one ADR-109 d.5 ranking table (fast track P8-A):
 * `GET /v1/demo/analysis/rankings?stream=&metric=`, bearer + `X-Shop-Id` like
 * `lib/shop-analysis/api-client.ts`. 404 → `null` (no table stored: the screen
 * says so); any other failure rejects — never the sample standing in.
 * Imported only by the signed-in Phân tích branch.
 */
export const DEMO_RANKINGS_API_PATH = "/v1/demo/analysis/rankings" as const;

export class RankingFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Ranking fetch failed (${status})`);
    this.name = "RankingFetchError";
  }
}

interface RankingRequest {
  token: string;
  shopId: string;
  stream: RankedStream;
  metric: RankedMetric;
  fetchImpl?: typeof fetch;
}

function isEnvelope(value: unknown): value is RankingEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const ranking = (value as { ranking?: unknown }).ranking;
  return (
    typeof ranking === "object" &&
    ranking !== null &&
    Array.isArray((ranking as { down?: unknown }).down) &&
    Array.isArray((ranking as { up?: unknown }).up) &&
    typeof (ranking as { closing?: unknown }).closing === "object"
  );
}

export async function fetchMetricRanking(request: RankingRequest): Promise<RankingEnvelope | null> {
  const { token, shopId, stream, metric, fetchImpl = fetch } = request;
  const query = new URLSearchParams({ stream, metric });
  const response = await fetchImpl(`${DEMO_RANKINGS_API_PATH}?${query.toString()}`, {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${token}`,
      "X-Shop-Id": shopId,
    },
    cache: "no-store",
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new RankingFetchError(response.status);
  const payload: unknown = await response.json();
  const body =
    typeof payload === "object" && payload !== null && "data" in payload
      ? (payload as { data: unknown }).data
      : payload;
  if (!isEnvelope(body)) throw new RankingFetchError(response.status);
  return body;
}
