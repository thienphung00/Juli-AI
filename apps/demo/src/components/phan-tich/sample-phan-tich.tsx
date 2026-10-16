"use client";

import type { DemoDecisionItem } from "@juli/contracts";
import { useMemo, useSyncExternalStore } from "react";

import type { QueryState } from "../../lib/phan-tich/model";
import { createSampleAnalysisClients } from "../../lib/content-analysis/sample";
import { sampleReport, sampleRankings } from "../../lib/phan-tich/sample-data";
import type { RankingLoader } from "../../lib/phan-tich/types";
import { reviewerSampleClients, reviewerSampleEpoch, subscribeReviewerSample } from "../../lib/reviewer/sample-store";
import { PhanTichView } from "./phan-tich-view";

/**
 * The signed-out Phân tích ("Bản minh họa", ADR-109 Amendment 2): the same
 * invented cosmetics shop as the signed-out Quyết định — its report and
 * rankings (`lib/phan-tich/sample-data.ts`) and its cards
 * (`lib/quyet-dinh/sample-data.ts`), so "Xem đề xuất ›" lands on a real sample
 * card. Bundled, never fetched: no module reachable from here performs a
 * request (an entry of `replay-module-graph.test.ts`).
 *
 * P37 (D47.2): the cards come from the tab's sample store, the one Quyết định
 * changes — only the cards still on the desk, as the real
 * `GET /v1/demo/decisions` lists them (a rejected, reverted, approved or
 * expired-by-status card loses its "Xem đề xuất ›").
 */

const RANKINGS = sampleRankings();
const SAMPLE_ANALYSIS = createSampleAnalysisClients();

export const loadSampleRanking: RankingLoader = async (stream, metric) => RANKINGS[stream]?.[metric] ?? null;

/** The sample store's cards on the desk, as `GET /v1/demo/decisions` items. */
export const loadSampleDecisions = (): Promise<readonly DemoDecisionItem[]> => reviewerSampleClients().fetchDeskDecisions();

export function SamplePhanTich({
  query,
  onNavigate,
}: {
  readonly query: QueryState;
  readonly onNavigate?: (href: string) => void;
}) {
  const report = useMemo(() => sampleReport(), []);
  const epoch = useSyncExternalStore(subscribeReviewerSample, reviewerSampleEpoch, reviewerSampleEpoch);
  return (
    <PhanTichView
      key={epoch}
      analysisClients={SAMPLE_ANALYSIS}
      loadDecisions={loadSampleDecisions}
      loadRanking={loadSampleRanking}
      onNavigate={onNavigate}
      query={query}
      report={report}
      sample
    />
  );
}
