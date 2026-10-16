"use client";

import { useState, useSyncExternalStore } from "react";

import type { SampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import { SAMPLE_SHOP, SAMPLE_TOKEN } from "../../lib/quyet-dinh/sample-data";
import { useReviewer } from "../../lib/reviewer/mode";
import { simulateSampleDecision } from "../../lib/reviewer/sample-simulation";
import { reviewerSampleClients, reviewerSampleEpoch, subscribeReviewerSample } from "../../lib/reviewer/sample-store";
import { QuyetDinhView, type QdQuery } from "./quyet-dinh-view";
import { SimulationDialog } from "./simulation-dialog";

/**
 * The signed-out Quyết định ("Bản minh họa", ADR-094 d.1): the same P10
 * screens as the signed-in door (`QuyetDinhView`), fed by the bundled sample
 * (`sample-data.ts`) through in-memory clients. Approve / reject / confirm /
 * upload / "Tôi đã áp dụng" / Hoàn tác change local state only; no module
 * reachable from here performs a request (an entry of
 * `replay-module-graph.test.ts`).
 *
 * P32-D (D42 amendment): a partner trial account with no pinned shop lands
 * here too; "Duyệt" opens the reviewer's simulated Duyệt → Thực thi over the
 * sample card ("Mô phỏng · không gửi tới TikTok") — computed in memory,
 * nothing sent.
 *
 * P32-E (D42 amendment 2): for that reviewer every other write works too —
 * on the session's shared sample store (`lib/reviewer/sample-store.ts`), so a
 * run started here survives a visit to Trang chủ and Cài đặt's rules are the
 * same ones. After "Thực thi (mô phỏng)" the dialog offers "Theo dõi lượt
 * chạy (mô phỏng)": the sample run (consent with edits, photo, Seller Center,
 * content drafts, Hoàn tác, Đo lường) — still in memory, still nothing sent.
 *
 * P37 (D47.2): the signed-out visitor uses the same tab-wide store, so Trang
 * chủ / Phân tích / Quyết định agree on every card, and the store walks the
 * real card lifecycle (queued → running → applied / rejected / back to
 * pending / expired; `sample-clients.ts`).
 */
export function SampleQuyetDinh({
  query,
  onNavigate,
  clients,
}: {
  readonly query: QdQuery;
  readonly onNavigate: (href: string) => void;
  /** Tests inject a store with `stepMs: 0`. */
  readonly clients?: SampleQdClients;
}) {
  const reviewer = useReviewer();
  const simulated = reviewer?.sample === true;
  const [own] = useState<SampleQdClients | null>(() => clients ?? null);
  const epoch = useSyncExternalStore(subscribeReviewerSample, reviewerSampleEpoch, reviewerSampleEpoch);
  const store = own ?? reviewerSampleClients();
  const [simulating, setSimulating] = useState<{ cardId: string; proceed: () => void } | null>(null);
  return (
    <>
      <QuyetDinhView
        clients={store}
        key={own ? "sample" : `sample-${epoch}`}
        onNavigate={onNavigate}
        onSimulateApprove={reviewer ? (cardIds, proceed) => setSimulating({ cardId: cardIds[0], proceed }) : undefined}
        onSimulateMeasure={simulated ? (stage) => store.simulateMeasurement(stage) : undefined}
        query={query}
        sample
        shop={SAMPLE_SHOP}
        simulated={simulated}
        token={SAMPLE_TOKEN}
      />
      {reviewer && simulating ? (
        <SimulationDialog
          cardId={simulating.cardId}
          onClose={() => setSimulating(null)}
          onContinue={
            simulated
              ? () => {
                  setSimulating(null);
                  simulating.proceed();
                }
              : undefined
          }
          simulate={simulateSampleDecision}
        />
      ) : null}
    </>
  );
}
