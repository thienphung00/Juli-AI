"use client";

/**
 * Connects a run id to the staged run view (issue #1316, ADR-076 decision
 * 3), on either of ADR-094's two doors.
 *
 * SIGNED-IN (a `token` is present): fetches the run's bound product name
 * (`GET /v1/demo/runs`, #1310/#1318's existing client, reused rather than
 * duplicated) and connects `useRunStream` (#1315) for the live event list.
 * Exactly #1316's original behavior, untouched by issue #1752 -- see
 * `SignedInRunDetail` below.
 *
 * REPLAY (no `token`): ADR-094 decision 1's anonymous door has no session
 * and calls no authenticated route, ever -- so this branch never touches
 * `fetchRuns`. Issue #1752 seeds the view instead from the one captured
 * golden scenario (`lib/run-surface/replay-scenario.ts`), paced locally by
 * `useReplayEvents`. `token` absence is the same signal `useRunStream`
 * itself already gates on (see that module's own docstring) -- reusing it
 * here, rather than inventing a second "am I in replay mode" flag, keeps
 * one source of truth for "is this connected to anything real".
 *
 * Split into two subcomponents rather than one big conditional so each
 * side owns its own, internally consistent set of hooks -- no hook here is
 * ever conditionally skipped within a single component instance.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { WorkflowRunListItem } from "@juli/contracts";

import { DestinationPlaceholder } from "./destination-placeholder";
import { RunStagedView } from "./run-staged-view";
import { fetchDemoRuns } from "../lib/run-ledger/api-client";
import { RUN_LEDGER_LOADING } from "../lib/run-ledger/copy";
import { useRunStream } from "../lib/run-surface/use-run-stream";
import { useReplayEvents } from "../lib/run-surface/use-replay-events";
import {
  REPLAY_SCENARIO_PRODUCT_NAME,
  REPLAY_SCENARIO_RUN_ID,
} from "../lib/run-surface/replay-scenario";

export interface RunDetailRouteProps {
  readonly runId: string;
  /** Injectable for tests; defaults to the real client. Never called on
   *  the replay path (no token) -- see the module docstring. */
  readonly fetchRuns?: typeof fetchDemoRuns;
  /** Injectable bearer token. Absent means the replay door (ADR-094
   *  decision 1); present means the signed-in door. */
  readonly token?: string;
}

const NOT_FOUND_PLACEHOLDER = (
  <DestinationPlaceholder
    description="Luồng thực hiện này không còn trong Demo hoặc chưa được tạo. Hãy quay lại Quyết định để xem các luồng đang chạy."
    recoveryHref="/decisions"
    recoveryLabel="Về Quyết định"
    state="empty"
    title="Không tìm thấy luồng thực hiện"
  />
);

type RunLookupStatus = "loading" | "found" | "not_found" | "error";

function useRunLookup(
  runId: string,
  fetchRuns: typeof fetchDemoRuns,
): { status: RunLookupStatus; run: WorkflowRunListItem | null } {
  const [status, setStatus] = useState<RunLookupStatus>("loading");
  const [run, setRun] = useState<WorkflowRunListItem | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const runs = await fetchRuns();
        if (cancelled) return;
        const match = runs.find((r) => r.id === runId) ?? null;
        setRun(match);
        setStatus(match ? "found" : "not_found");
      } catch {
        if (!cancelled) setStatus("error");
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [runId, fetchRuns]);

  return { status, run };
}

/** ADR-094 decision 1's anonymous door. No token, no session, no
 *  `fetchRuns` call, no `useRunStream` connection -- ever. */
function ReplayRunDetail({
  requestedStageId,
  runId,
}: {
  readonly requestedStageId: string | null;
  readonly runId: string;
}) {
  const { events } = useReplayEvents();

  if (runId !== REPLAY_SCENARIO_RUN_ID) {
    return NOT_FOUND_PLACEHOLDER;
  }

  return (
    <RunStagedView
      events={events}
      isReconnecting={false}
      productName={REPLAY_SCENARIO_PRODUCT_NAME}
      requestedStageId={requestedStageId}
      runId={runId}
    />
  );
}

/** The signed-in door -- #1316's original behavior, unchanged by #1752. */
function SignedInRunDetail({
  fetchRuns,
  requestedStageId,
  runId,
  token,
}: {
  readonly fetchRuns: typeof fetchDemoRuns;
  readonly requestedStageId: string | null;
  readonly runId: string;
  readonly token: string;
}) {
  const { status, run } = useRunLookup(runId, fetchRuns);
  const { events, streamStatus } = useRunStream(runId, { enabled: true, token });

  if (status === "loading") {
    return (
      <p role="status" className="run-ledger__loading">
        {RUN_LEDGER_LOADING}
      </p>
    );
  }

  if (status === "not_found" || status === "error" || !run) {
    return NOT_FOUND_PLACEHOLDER;
  }

  return (
    <RunStagedView
      confirmationToken={token}
      events={events}
      isReconnecting={streamStatus === "reconnecting"}
      productName={run.product_name}
      requestedStageId={requestedStageId}
      runId={runId}
    />
  );
}

export function RunDetailRoute({ runId, fetchRuns = fetchDemoRuns, token }: RunDetailRouteProps) {
  const searchParams = useSearchParams();
  const requestedStageId = searchParams.get("stage");

  if (!token) {
    return <ReplayRunDetail requestedStageId={requestedStageId} runId={runId} />;
  }

  return (
    <SignedInRunDetail
      fetchRuns={fetchRuns}
      requestedStageId={requestedStageId}
      runId={runId}
      token={token}
    />
  );
}
