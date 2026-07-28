import type { DemoAnalyticsEnvelope } from "@juli/contracts";

import type { AnalyticsRange } from "./main-kpis";

export const DEMO_ANALYTICS_API_PATH = "/v1/demo/analytics" as const;

const API_BASE =
  typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_URL
    ? process.env.NEXT_PUBLIC_API_URL
    : "http://localhost:8000";

export class DemoAnalyticsFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Demo analytics fetch failed (${status})`);
    this.name = "DemoAnalyticsFetchError";
  }
}

export function buildDemoAnalyticsUrl(range?: AnalyticsRange): string {
  const base = `${API_BASE}${DEMO_ANALYTICS_API_PATH}`;
  return range ? `${base}?range=${range}` : base;
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
