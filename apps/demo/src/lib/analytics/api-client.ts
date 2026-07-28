import type { DemoAnalyticsEnvelope } from "@juli/contracts";

import type { AnalyticsRange } from "./main-kpis";

export const DEMO_ANALYTICS_API_PATH = "/v1/demo/analytics" as const;

export class DemoAnalyticsFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Demo analytics fetch failed (${status})`);
    this.name = "DemoAnalyticsFetchError";
  }
}

/**
 * Same-origin relative URL only — no client env API base
 * (demo workspace contract #397). Proxy `/v1/*` at the edge or enable API CORS.
 */
export function buildDemoAnalyticsUrl(range?: AnalyticsRange): string {
  return range
    ? `${DEMO_ANALYTICS_API_PATH}?range=${range}`
    : DEMO_ANALYTICS_API_PATH;
}

export async function fetchDemoAnalytics(
  range?: AnalyticsRange,
  fetchImpl: typeof fetch = fetch,
): Promise<DemoAnalyticsEnvelope> {
  const response = await fetchImpl(buildDemoAnalyticsUrl(range), {
    headers: { Accept: "application/json" },
    cache: "no-store",
  });

  if (!response.ok) {
    throw new DemoAnalyticsFetchError(response.status);
  }

  return response.json() as Promise<DemoAnalyticsEnvelope>;
}

/** Paths Fake Demo Refresh must never call (#534). */
export const DEMO_ANALYTICS_FORBIDDEN_REFRESH_PATHS = [
  "/v1/demo/analytics/recompute",
  "/v1/demo/analytics/force-recompute",
  "/v1/demo/refresh",
  "/v1/partner",
] as const;

export function isForbiddenDemoRefreshPath(url: string): boolean {
  return DEMO_ANALYTICS_FORBIDDEN_REFRESH_PATHS.some((fragment) =>
    url.includes(fragment),
  );
}
