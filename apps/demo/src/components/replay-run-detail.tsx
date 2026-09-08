"use client";

/**
 * ADR-094 decision 1's anonymous replay door. No token, no session, no
 * `fetchRuns` call, no `useRunStream` connection, and (issue #1764) no
 * confirmation POST -- ever.
 *
 * SPLIT OUT OF `run-detail-route.tsx` ON PURPOSE (issue #1764). That file
 * composes BOTH doors in one module, so it unconditionally imports the
 * signed-in door's own clients (`fetchDemoRuns`, `useRunStream`) even
 * though the replay door never calls them at runtime -- a static import
 * graph can't see that "never calls" and would flag them as reachable
 * regardless. This file is the replay door's OWN module, importing only
 * what a replay visitor's browser actually needs: `useReplayEvents` (issue
 * #1752) for the paced event feed, and `replay-confirm.ts` (issue #1764)
 * for a confirm handler that resolves a decision from the scenario's own
 * captured continuation, never the network.
 *
 * `src/__tests__/replay-module-graph.test.ts` uses this file itself as its
 * "run route" entry point: the reachable module graph from here must never
 * contain a call site that performs a network fetch, or a literal backend
 * route path (v1/...). Every import below is chosen to keep that true --
 * `confirmation-client.ts` (the one module that owns the real network call)
 * is never on this file's own import path, directly or transitively (see
 * `confirmation-decision.ts`'s and `replay-confirm.ts`'s own docstrings for
 * how `OptionPicker` avoids it too).
 */

import { RunStagedView } from "./run-staged-view";
import { DestinationPlaceholder } from "./destination-placeholder";
import { useReplayEvents } from "../lib/run-surface/use-replay-events";
import { buildReplayConfirm } from "../lib/run-surface/replay-confirm";
import {
  REPLAY_SCENARIO_PRODUCT_NAME,
  REPLAY_SCENARIO_RUN_ID,
} from "../lib/run-surface/replay-scenario";

const NOT_FOUND_PLACEHOLDER = (
  <DestinationPlaceholder
    description="Luồng thực hiện này không còn trong Demo hoặc chưa được tạo. Hãy quay lại Quyết định để xem các luồng đang chạy."
    recoveryHref="/decisions"
    recoveryLabel="Về Quyết định"
    state="empty"
    title="Không tìm thấy luồng thực hiện"
  />
);

export interface ReplayRunDetailProps {
  readonly requestedStageId: string | null;
  readonly runId: string;
}

export function ReplayRunDetail({ requestedStageId, runId }: ReplayRunDetailProps) {
  const { events, resolveDecision } = useReplayEvents();

  if (runId !== REPLAY_SCENARIO_RUN_ID) {
    return NOT_FOUND_PLACEHOLDER;
  }

  return (
    <RunStagedView
      confirm={buildReplayConfirm(runId, resolveDecision)}
      events={events}
      isReconnecting={false}
      productName={REPLAY_SCENARIO_PRODUCT_NAME}
      requestedStageId={requestedStageId}
      runId={runId}
    />
  );
}
