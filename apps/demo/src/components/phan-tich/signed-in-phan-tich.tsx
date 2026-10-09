"use client";

import { useCallback } from "react";

import type { QueryState } from "../../lib/phan-tich/model";
import { fetchMetricRanking } from "../../lib/phan-tich/rankings-client";
import type { RankingLoader } from "../../lib/phan-tich/types";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";
import { PhanTichView } from "./phan-tich-view";

/**
 * The signed-in Phân tích (AC-8.6): the acting shop's report from the shell
 * (`useShopReport`, fetched once) and its rankings read on demand per clicked
 * cell (`GET /v1/demo/analysis/rankings`, bearer + `X-Shop-Id`).
 */
export function SignedInPhanTich({
  envelope,
  token,
  shopId,
  query,
  onNavigate,
  fetchRanking = fetchMetricRanking,
}: {
  readonly envelope: ShopAnalysisEnvelope;
  readonly token: string;
  readonly shopId: string;
  readonly query: QueryState;
  readonly onNavigate?: (href: string) => void;
  /** Injectable for tests. */
  readonly fetchRanking?: typeof fetchMetricRanking;
}) {
  const loadRanking: RankingLoader = useCallback(
    (stream, metric) => fetchRanking({ token, shopId, stream, metric }),
    [fetchRanking, token, shopId],
  );
  return <PhanTichView envelope={envelope} loadRanking={loadRanking} onNavigate={onNavigate} query={query} />;
}
