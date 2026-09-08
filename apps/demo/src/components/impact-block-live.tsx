"use client";

import { useEffect } from "react";

import { useOptionalAnalyticsData } from "../lib/analytics/analytics-data-context";
import {
  buildImpactMetricSnapshot,
  type ImpactMetricSnapshot,
} from "../lib/analytics/envelope-mapper";
import type { PlanImpactContent } from "../lib/plan-reviews";

export interface LiveImpactFetcherProps {
  impact: PlanImpactContent;
  /** Stable — `impact-block.tsx` passes its `useState` setter directly. */
  onSnapshot: (snapshot: ImpactMetricSnapshot | null) => void;
}

/**
 * The signed-in door's impact DATA source (issue #1772, ADR-094 decision 1)
 * — headless by design, renders nothing of its own. Reads the real serving
 * envelope, the same one the Analytics screen reads, triggers the fetch on
 * mount (exactly as before this issue), and reports the derived snapshot up
 * to `PlanImpactBlock`'s single, persistently-mounted `ImpactBlockShell` via
 * `onSnapshot` — see `impact-block.tsx`'s own docstring for why the shell
 * itself is never re-mounted across this boundary.
 *
 * Loaded ONLY behind `PlanImpactBlock`'s dynamic `import()`, itself gated
 * on `readAuthSession()`. That is deliberate, not incidental: `import()`
 * calls are invisible to `replay-module-graph.test.ts`'s static-import
 * walker (it only follows `import ... from "..."` edges), so a replay
 * visitor with no session never has this file, `analytics-data-context.tsx`,
 * or `lib/analytics/api-client.ts` in their reachable graph — the review
 * page genuinely carries no fetch capability until a session exists,
 * structurally as well as at runtime.
 *
 * Reports `envelope` (a stable reference from `AnalyticsDataProvider`'s own
 * `useState`, changing only when a real fetch actually resolves) rather
 * than the freshly-computed `snapshot` object on every render — the latter
 * is a new object identity each time even when nothing changed, which
 * would re-trigger the reporting effect every render and loop forever.
 */
export function LiveImpactFetcher({ impact, onSnapshot }: LiveImpactFetcherProps) {
  const analytics = useOptionalAnalyticsData();
  const loadAnalytics = analytics?.loadAnalytics;
  const envelope = analytics?.envelope;

  // The decision surface is not an analytics screen, so nothing else has
  // asked for the envelope by the time the card mounts.
  useEffect(() => {
    void loadAnalytics?.();
  }, [loadAnalytics]);

  useEffect(() => {
    onSnapshot(buildImpactMetricSnapshot(envelope, impact.metricKey));
  }, [envelope, impact.metricKey, onSnapshot]);

  return null;
}

export default LiveImpactFetcher;
