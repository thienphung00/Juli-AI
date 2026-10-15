"use client";

import { useState } from "react";

import { createSampleQdClients, type SampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import { SAMPLE_SHOP, SAMPLE_TOKEN } from "../../lib/quyet-dinh/sample-data";
import { useReviewer } from "../../lib/reviewer/mode";
import { simulateSampleDecision } from "../../lib/reviewer/sample-simulation";
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
 * here too. Its shell makes every write control read-only except "Duyệt",
 * which opens the reviewer's simulated Duyệt → Thực thi over the sample card
 * ("Mô phỏng · không gửi tới TikTok") — computed in memory, nothing sent.
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
  const [store] = useState<SampleQdClients>(() => clients ?? createSampleQdClients());
  const reviewer = useReviewer();
  const [simulating, setSimulating] = useState<string | null>(null);
  return (
    <>
      <QuyetDinhView
        clients={store}
        onNavigate={onNavigate}
        onSimulateApprove={reviewer ? setSimulating : undefined}
        query={query}
        sample
        shop={SAMPLE_SHOP}
        token={SAMPLE_TOKEN}
      />
      {reviewer && simulating ? (
        <SimulationDialog cardId={simulating} onClose={() => setSimulating(null)} simulate={simulateSampleDecision} />
      ) : null}
    </>
  );
}
