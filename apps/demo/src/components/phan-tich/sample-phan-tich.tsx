"use client";

import type { DemoDecisionItem } from "@juli/contracts";
import { useMemo } from "react";

import type { QueryState } from "../../lib/phan-tich/model";
import { sampleReport, sampleRankings } from "../../lib/phan-tich/sample-data";
import type { RankingLoader } from "../../lib/phan-tich/types";
import { SAMPLE_CARDS, sampleDecision } from "../../lib/quyet-dinh/sample-data";
import { PhanTichView } from "./phan-tich-view";

/**
 * The signed-out Phân tích ("Bản minh họa", ADR-109 Amendment 2): the same
 * invented cosmetics shop as the signed-out Quyết định — its report and
 * rankings (`lib/phan-tich/sample-data.ts`) and its cards
 * (`lib/quyet-dinh/sample-data.ts`), so "Xem đề xuất ›" lands on a real sample
 * card. Bundled, never fetched: no module reachable from here performs a
 * request (an entry of `replay-module-graph.test.ts`).
 */

const RANKINGS = sampleRankings();

export const loadSampleRanking: RankingLoader = async (stream, metric) => RANKINGS[stream]?.[metric] ?? null;

/** The Quyết định sample's cards as `GET /v1/demo/decisions` items. */
export const loadSampleDecisions = async (): Promise<readonly DemoDecisionItem[]> => {
  const now = Date.now();
  return SAMPLE_CARDS.map((card) => sampleDecision(card, now));
};

export function SamplePhanTich({
  query,
  onNavigate,
}: {
  readonly query: QueryState;
  readonly onNavigate?: (href: string) => void;
}) {
  const report = useMemo(() => sampleReport(), []);
  return (
    <PhanTichView
      loadDecisions={loadSampleDecisions}
      loadRanking={loadSampleRanking}
      onNavigate={onNavigate}
      query={query}
      report={report}
      sample
    />
  );
}
