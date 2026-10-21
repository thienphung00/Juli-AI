"use client";

import { SANDBOX_NO_TRAFFIC_COPY } from "../../lib/reviewer/copy";
import { useSandboxReviewer } from "../../lib/reviewer/mode";
import { buildHomeOverview } from "../../lib/shop-report/home-metrics";
import type { ShopAnalysisEnvelope } from "../../lib/shop-analysis/types";

/** True when no stream has a single impression: the sandbox has no traffic. */
export function envelopeHasNoTraffic(envelope: ShopAnalysisEnvelope): boolean {
  const model = buildHomeOverview(envelope);
  const cells = model.groups.flatMap((group) => group.rows.flatMap((row) => (row.missing ? [] : row.cells)));
  return cells.filter((cell) => cell.metric === "impressions").every((cell) => !cell.last);
}

/**
 * P64 (D73): the honest empty state for the reviewer's live sandbox when it
 * has no traffic — nothing is invented, orders and products stay live.
 */
export function SandboxTrafficNote({ envelope }: { readonly envelope: ShopAnalysisEnvelope }) {
  const sandbox = useSandboxReviewer();
  if (!sandbox || !envelopeHasNoTraffic(envelope)) return null;
  return (
    <p className="demo-notice" data-testid="sandbox-no-traffic" role="status">
      {SANDBOX_NO_TRAFFIC_COPY}
    </p>
  );
}
