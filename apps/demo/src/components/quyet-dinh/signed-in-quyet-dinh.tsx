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
import { approveDemoDecision, fetchRecommendations } from "../../lib/recommendations-api-client";
import { fetchDemoRuns } from "../../lib/run-ledger/api-client";
import { submitConfirmationDecision } from "../../lib/run-surface/confirmation-client";
import { useRunStream } from "../../lib/run-surface/use-run-stream";
import { AppPageHeader } from "../app-shell/page-header";
import { QuyetDinhView, type QdQuery } from "./quyet-dinh-view";

export type { QdClients } from "../../lib/quyet-dinh/client-types";
export { qdHref, resolveMeasureTab, type QdQuery } from "./quyet-dinh-view";

/** The run's live SSE stream (`useRunStream`), as Quyết định reads it. */
function useLiveRunEvents(runId: string, auth: AuthedOptions, streamFetch?: typeof fetch): RunEventsState {
  const { events, streamStatus } = useRunStream(runId, { token: auth.token, shopId: auth.shopId, fetchImpl: streamFetch });
  return { events, streamStatus };
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
};

export function SignedInQuyetDinh({
  token,
  shop,
  query,
  onNavigate,
  clients = REAL_QD_CLIENTS,
}: {
  readonly token: string;
  readonly shop: { readonly id: string; readonly name: string } | null;
  readonly query: QdQuery;
  readonly onNavigate: (href: string) => void;
  readonly clients?: QdClients;
}) {
  if (!shop) {
    return (
      <section aria-labelledby="qd-title" className="qd-page">
        <AppPageHeader eyebrow="Quyết định" title="Việc cần bạn quyết định" titleId="qd-title" />
        <div className="qv-empty" role="status">
          <p>Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.</p>
          <Link className="qv-link" href="/auth/connect-shop">
            Kết nối TikTok Shop
          </Link>
        </div>
      </section>
    );
  }
  return <QuyetDinhView clients={clients} onNavigate={onNavigate} query={query} shop={shop} token={token} />;
}
