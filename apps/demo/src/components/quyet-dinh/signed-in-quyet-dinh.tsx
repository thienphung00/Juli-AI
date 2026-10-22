"use client";

/**
 * The signed-in Quyết định (AC-8.7 → AC-10.3, ADR-109 Amendment 1) — the one
 * module that wires the real clients into `QuyetDinhView`: decisions +
 * approve / reject, the run ledger poll, each run's SSE stream,
 * confirmations (with edited values), decline, photo upload, Seller Center
 * instructions / applied, changes, Hoàn tác with a reason, revert questions
 * and the measurement. Every client is injectable (`clients`) for tests. The
 * anonymous door never imports this module (`replay-module-graph.test.ts`);
 * it renders `SampleQuyetDinh` over the same view.
 */

import Link from "next/link";
import { useMemo, useState } from "react";

import {
  declineRun,
  deleteShopRule,
  dismissRevertQuestion,
  fetchRevertQuestions,
  fetchRunChanges,
  fetchRunDetail,
  fetchRunInstructions,
  fetchRunMeasurement,
  fetchShopRules,
  markContentPublished,
  markRunApplied,
  putShopRule,
  redraftContentScript,
  rejectDecision,
  startRunRevert,
  uploadRunPhoto,
  chooseContentScript,
} from "../../lib/quyet-dinh/api-client";
import type { AuthedOptions, QdClients, RunEventsState } from "../../lib/quyet-dinh/client-types";
import { createAnalysisClients } from "../../lib/content-analysis/api-client";
import { approveDemoDecision, fetchRecommendations } from "../../lib/recommendations-api-client";
import { fetchDemoRuns } from "../../lib/run-ledger/api-client";
import { submitConfirmationDecision } from "../../lib/run-surface/confirmation-client";
import { useRunStream } from "../../lib/run-surface/use-run-stream";
import { REVIEWER_READ_ONLY_TITLE, REVIEWER_SANDBOX_READ_ONLY_TITLE } from "../../lib/reviewer/copy";
import { isSandboxReviewer, useReviewer } from "../../lib/reviewer/mode";
import { AppPageHeader } from "../app-shell/page-header";
import { SellerViewProvider } from "../seller-view-context";
import { QuyetDinhView, type QdQuery } from "./quyet-dinh-view";
import { ReviewerSimulation } from "./reviewer-simulation";

export type { QdClients } from "../../lib/quyet-dinh/client-types";
export { qdHref, resolveMeasureTab, type QdQuery } from "./quyet-dinh-view";

/** The run's live SSE stream (`useRunStream`), as Quyết định reads it. */
function useLiveRunEvents(runId: string, auth: AuthedOptions, streamFetch?: typeof fetch): RunEventsState {
  const { events, streamStatus } = useRunStream(runId, { token: auth.token, shopId: auth.shopId, fetchImpl: streamFetch });
  return { events, streamStatus };
}

/** P32-A: a reviewer opens no run stream (the API refuses it); runs are read as they are. */
function useNoRunEvents(): RunEventsState {
  return { events: [], streamStatus: "closed" };
}

export const REAL_QD_CLIENTS: QdClients = {
  fetchDecisions: fetchRecommendations,
  approve: approveDemoDecision,
  reject: rejectDecision,
  fetchRuns: fetchDemoRuns,
  fetchRules: fetchShopRules,
  putRule: putShopRule,
  deleteRule: deleteShopRule,
  fetchChanges: fetchRunChanges,
  startRevert: startRunRevert,
  fetchQuestions: fetchRevertQuestions,
  dismissQuestion: dismissRevertQuestion,
  confirm: submitConfirmationDecision,
  decline: declineRun,
  uploadPhoto: uploadRunPhoto,
  fetchInstructions: fetchRunInstructions,
  markApplied: markRunApplied,
  fetchMeasurement: fetchRunMeasurement,
  fetchRunDetail,
  useContent: chooseContentScript,
  redraftContent: redraftContentScript,
  markPublished: markContentPublished,
  useRunEvents: useLiveRunEvents,
  analysisClients: createAnalysisClients,
};

export function SignedInQuyetDinh({
  token,
  shop,
  query,
  onNavigate,
  clients = REAL_QD_CLIENTS,
  cardsRefresh,
}: {
  readonly token: string;
  readonly shop: { readonly id: string; readonly name: string } | null;
  readonly query: QdQuery;
  readonly onNavigate: (href: string) => void;
  readonly clients?: QdClients;
  /** P17: bumped by the onboarding poll — re-read the cards without a loading state. */
  readonly cardsRefresh?: number;
}) {
  const reviewer = useReviewer();
  const [simulating, setSimulating] = useState<string | null>(null);
  const reviewerClients = useMemo<QdClients>(() => ({ ...clients, useRunEvents: useNoRunEvents }), [clients]);
  if (!shop) {
    return (
      <section aria-labelledby="qd-title" className="qd-page">
        <AppPageHeader eyebrow="Quyết định" title="Việc cần bạn quyết định" titleId="qd-title" />
        <div className="qv-empty" role="status">
          <p>Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.</p>
          {reviewer ? null : (
            <Link className="qv-link" href="/auth/connect-shop">
              Kết nối TikTok Shop
            </Link>
          )}
        </div>
      </section>
    );
  }
  if (reviewer && isSandboxReviewer(reviewer)) {
    // P64 (D73.4): on Juli's live TikTok sandbox shop the partner account runs the
    // seller's own flow — Duyệt starts the agent run, the run streams over SSE in
    // "Đang thực hiện" and waits for the same confirmation. Every other write
    // (rules, revert, Seller Center) stays read-only; the API refuses them anyway.
    return (
      <SellerViewProvider readOnly readOnlyTitle={REVIEWER_SANDBOX_READ_ONLY_TITLE} runActions>
        <QuyetDinhView
          cardsRefresh={cardsRefresh}
          clients={clients}
          onNavigate={onNavigate}
          openRunOnApprove
          query={query}
          shop={shop}
          token={token}
        />
      </SellerViewProvider>
    );
  }
  if (reviewer) {
    // P32-A (D42): the partner trial account — every write read-only, "Duyệt"
    // runs the simulated Duyệt → Thực thi. The API refuses the rest anyway.
    return (
      <SellerViewProvider readOnly readOnlyTitle={REVIEWER_READ_ONLY_TITLE} simulateApprove>
        <QuyetDinhView
          cardsRefresh={cardsRefresh}
          clients={reviewerClients}
          onNavigate={onNavigate}
          onSimulateApprove={(cardIds) => setSimulating(cardIds[0])}
          query={query}
          shop={shop}
          token={token}
        />
        {simulating ? (
          <ReviewerSimulation
            cardId={simulating}
            onClose={() => setSimulating(null)}
            shopId={shop.id}
            token={token}
          />
        ) : null}
      </SellerViewProvider>
    );
  }
  return (
    <QuyetDinhView
      cardsRefresh={cardsRefresh}
      clients={clients}
      onNavigate={onNavigate}
      query={query}
      shop={shop}
      token={token}
    />
  );
}
