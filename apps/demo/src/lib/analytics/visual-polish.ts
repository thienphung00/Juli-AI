import type { ChartTrend } from "@juli/ui";

export function analyticsDeltaClass(trend: ChartTrend): string {
  return `analytics-delta analytics-delta--${trend}`;
}
