"use client";

import { useState } from "react";

import { createSampleQdClients, type SampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import { SAMPLE_SHOP, SAMPLE_TOKEN } from "../../lib/quyet-dinh/sample-data";
import { QuyetDinhView, type QdQuery } from "./quyet-dinh-view";

/**
 * The signed-out Quyết định ("Bản minh họa", ADR-094 d.1): the same P10
 * screens as the signed-in door (`QuyetDinhView`), fed by the bundled sample
 * (`sample-data.ts`) through in-memory clients. Approve / reject / confirm /
 * upload / "Tôi đã áp dụng" / Hoàn tác change local state only; no module
 * reachable from here performs a request (an entry of
 * `replay-module-graph.test.ts`).
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
  return <QuyetDinhView clients={store} onNavigate={onNavigate} query={query} sample shop={SAMPLE_SHOP} token={SAMPLE_TOKEN} />;
}
