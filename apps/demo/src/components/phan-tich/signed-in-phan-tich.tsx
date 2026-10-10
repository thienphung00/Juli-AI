"use client";

import { useCallback } from "react";

import type { QueryState } from "../../lib/phan-tich/model";
import { fetchMetricRanking } from "../../lib/phan-tich/rankings-client";
import type { RankingLoader } from "../../lib/phan-tich/types";
import { fetchRecommendations } from "../../lib/recommendations-api-client";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { PhanTichView } from "./phan-tich-view";

/**
 * The signed-in Phân tích (ADR-109 Amendment 2): the acting shop's report
 * from the shell (`useShopReport`, fetched once), its rankings read on demand
 * per open stream × cell (`GET /v1/demo/analysis/rankings`) and its cards
 * (`GET /v1/demo/decisions`, for "Xem đề xuất ›"), bearer + `X-Shop-Id`.
 */
export function SignedInPhanTich({
  envelope,
  token,
  shopId,
  query,
  onNavigate,
  fetchRanking = fetchMetricRanking,
  fetchDecisions = fetchRecommendations,
}: {
  readonly envelope: ShopAnalysisEnvelope;
  readonly token: string;
  readonly shopId: string;
  readonly query: QueryState;
  readonly onNavigate?: (href: string) => void;
  /** Injectable for tests. */
  readonly fetchRanking?: typeof fetchMetricRanking;
  readonly fetchDecisions?: typeof fetchRecommendations;
}) {
  const loadRanking: RankingLoader = useCallback(
    (stream, metric) => fetchRanking({ token, shopId, stream, metric }),
    [fetchRanking, token, shopId],
  );
  const loadDecisions = useCallback(() => fetchDecisions({ token, shopId }), [fetchDecisions, token, shopId]);
  return (
    <PhanTichView
      loadDecisions={loadDecisions}
      loadRanking={loadRanking}
      onNavigate={onNavigate}
      query={query}
      report={envelope.report}
    />
  );
}
