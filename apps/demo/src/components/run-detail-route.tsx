"use client";

/**
 * Connects a real backend run id to the staged run view (issue #1316,
 * ADR-076 decision 3). Thin on purpose: it owns exactly two things
 * `RunStagedView` cannot own itself -- fetching the run's bound product
 * name (`GET /v1/demo/runs`, #1310/#1318's existing client, reused rather
 * than duplicated) and connecting `useRunStream` (#1315) for the event
 * list. Everything about stage content, navigation, and locking is
 * `RunStagedView`'s job.
 *
 * NO TOKEN SOURCE EXISTS YET (ADR-094): the demo surface is anonymous
 * client replay with no session, and the signed-in path's real runs wait
 * on connect-shop. `useRunStream` without a token stays `idle` by its own
 * contract -- this component is therefore honestly inert against the real
 * backend today, and becomes live the moment a token is wired in, with no
 * further change here.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { WorkflowRunListItem } from "@juli/contracts";

import { DestinationPlaceholder } from "./destination-placeholder";
import { RunStagedView } from "./run-staged-view";
import { fetchDemoRuns } from "../lib/run-ledger/api-client";
import { RUN_LEDGER_LOADING } from "../lib/run-ledger/copy";
import { useRunStream } from "../lib/run-surface/use-run-stream";

export interface RunDetailRouteProps {
  readonly runId: string;
  /** Injectable for tests; defaults to the real client. */
  readonly fetchRuns?: typeof fetchDemoRuns;
  /** Injectable bearer token -- absent means "not connected yet" (see the
   *  module docstring). No caller supplies this today. */
  readonly token?: string;
}

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

export function RunDetailRoute({ runId, fetchRuns = fetchDemoRuns, token }: RunDetailRouteProps) {
  const { status, run } = useRunLookup(runId, fetchRuns);
  const searchParams = useSearchParams();
  const requestedStageId = searchParams.get("stage");

  const { events, streamStatus } = useRunStream(runId, { enabled: true, token });

  if (status === "loading") {
    return (
      <p role="status" className="run-ledger__loading">
        {RUN_LEDGER_LOADING}
      </p>
    );
  }

  if (status === "not_found" || status === "error" || !run) {
    return (
      <DestinationPlaceholder
        description="Luồng thực hiện này không còn trong Demo hoặc chưa được tạo. Hãy quay lại Quyết định để xem các luồng đang chạy."
        recoveryHref="/decisions"
        recoveryLabel="Về Quyết định"
        state="empty"
        title="Không tìm thấy luồng thực hiện"
      />
    );
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
