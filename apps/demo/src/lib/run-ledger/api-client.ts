import type { WorkflowRunListItem, WorkflowRunListResponse } from "@juli/contracts";

/**
 * Fetch client for `GET /v1/demo/runs` (issue #1310, consumed read-only by
 * the run ledger, issue #1318). Same-origin relative URL only -- no client
 * env API base (demo workspace contract #397), matching the existing
 * `fetchDemoAnalytics` convention (`lib/analytics/api-client.ts`).
 *
 * This is a plain JSON GET against the polled read model -- deliberately
 * NOT `agent-event-stream.ts`'s SSE transport. The ledger polls; it does
 * not open an event stream to list runs (that stream is per-run, opened at
 * most for one active run's detail view once that surface exists).
 */
export const DEMO_RUNS_API_PATH = "/v1/demo/runs" as const;

export class DemoRunsFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Demo runs list fetch failed (${status})`);
    this.name = "DemoRunsFetchError";
  }
}

export async function fetchDemoRuns(
  fetchImpl: typeof fetch = fetch,
): Promise<WorkflowRunListItem[]> {
  const response = await fetchImpl(DEMO_RUNS_API_PATH, {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new DemoRunsFetchError(response.status);
  }

  const body = (await response.json()) as WorkflowRunListResponse;
  return body.data;
}
