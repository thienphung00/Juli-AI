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

interface FetchDemoRunsOptions {
  /** Bearer token — the route is authenticated (ADR-075 decision 3); the
   *  pre-#1909 client sent no credentials at all, which is why the
   *  "live-backed" signed-in door could never actually resolve a run. */
  token?: string;
  /** The acting shop (`lib/shop-session.ts`) — `get_active_shop`
   *  ownership-checks it as `X-Shop-Id`. */
  shopId?: string;
  fetchImpl?: typeof fetch;
}

export async function fetchDemoRuns(
  options: FetchDemoRunsOptions = {},
): Promise<WorkflowRunListItem[]> {
  const { token, shopId, fetchImpl = fetch } = options;

  const headers = new Headers({ Accept: "application/json" });
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (shopId) headers.set("X-Shop-Id", shopId);

  const response = await fetchImpl(DEMO_RUNS_API_PATH, {
    headers,
    cache: "no-store",
  });

  if (!response.ok) {
    throw new DemoRunsFetchError(response.status);
  }

  const body = (await response.json()) as WorkflowRunListResponse;
  return body.data;
}
