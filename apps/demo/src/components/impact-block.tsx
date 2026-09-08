"use client";

import { Suspense, lazy, useEffect, useState } from "react";

import type { ImpactMetricSnapshot } from "../lib/analytics/envelope-mapper";
import type { PlanImpactContent } from "../lib/plan-reviews";
import { readAuthSession } from "../lib/supabase-auth";
import { IMPACT_UNAVAILABLE_TEXT, ImpactBlockShell } from "./impact-block-shell";

export { IMPACT_UNAVAILABLE_TEXT };

interface PlanImpactBlockProps {
  impact: PlanImpactContent;
}

// `React.lazy` + a plain `import()` call — not a static `import ... from`
// — so `replay-module-graph.test.ts`'s walker (which only follows static
// import edges) never resolves into `impact-block-live.tsx`,
// `analytics-data-context.tsx`, or `lib/analytics/api-client.ts`. See
// `impact-block-live.tsx`'s own docstring for why that is load-bearing, not
// incidental.
const LiveImpactFetcher = lazy(() =>
  import("./impact-block-live").then((mod) => ({
    default: mod.LiveImpactFetcher,
  })),
);

/**
 * The plan review card's impact block (ADR-055 items 15–17, issue #771) —
 * the card's centre of gravity, sitting directly under the header, above
 * the proposal.
 *
 * Issue #1772 (ADR-094 decision 1): the review page is reached by the
 * anonymous replay door as well as a future signed-in one, and only the
 * signed-in surface has anywhere to fetch analytics FOR — the replay
 * visitor has no session and no shop, so a "real current value" would be
 * either a network call ADR-094 forbids outright, or a fabricated reading.
 * The discriminator is **whether this surface has a session**, read once on
 * mount via `readAuthSession()` (the same signal `ConnectShopPage` and
 * `RunDetailRoute`'s `token` already use — one source of truth for "is this
 * connected to anything real," not a second, page-shaped flag).
 *
 * `ImpactBlockShell` is rendered exactly ONCE here, unconditionally — its
 * `snapshot` prop is plain local state, updated in place as the real value
 * arrives. `LiveImpactFetcher` (loaded only when a session exists) renders
 * NO visible output of its own; it exists purely to read the analytics
 * context and report a snapshot up via `onSnapshot`. That split is
 * deliberate, not incidental: an earlier version of this fix rendered
 * `ImpactBlockShell` from two different places — the shell directly for
 * "no session yet", and again from inside the lazy-loaded, network-capable
 * component for "session confirmed" — and Suspense does not reconcile a
 * fallback into its resolved children; it unmounts one CardBody and mounts
 * a completely different one. A reference to the card taken before that
 * swap (the seller's screen reader focus, a test's captured DOM node — see
 * `plan-impact-block.test.tsx`) never saw the swapped-in one update.
 * Keeping exactly one `ImpactBlockShell` instance, always mounted, makes
 * the value arriving a normal prop update instead of a replace.
 *
 * Three things it deliberately never does:
 * - **No projected magnitude.** Juli does not quote an amount it cannot stand
 *   behind (PRD user story 22; ADR-055 item 16).
 * - **No placeholder value.** A missing reading renders as a missing reading,
 *   whether the cause is no session or an envelope with nothing for this KPI.
 * - **No second state.** It does not change after approval (ADR-055 item 17):
 *   Mock-mode executions are dry-run, so any later KPI movement is the
 *   reference shop's real trading, and showing it as the seller's achievement
 *   would be a fabricated causal claim.
 */
export function PlanImpactBlock({ impact }: PlanImpactBlockProps) {
  const [hasSession, setHasSession] = useState(false);
  const [snapshot, setSnapshot] = useState<ImpactMetricSnapshot | null>(null);

  // Deferred via setTimeout(0) rather than calling the setter synchronously
  // in the effect body -- the same pattern demo-landing.tsx already uses
  // for its own browser-storage read (react-hooks/set-state-in-effect).
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setHasSession(Boolean(readAuthSession()));
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  return (
    <>
      <ImpactBlockShell impact={impact} snapshot={snapshot} />
      {hasSession ? (
        <Suspense fallback={null}>
          <LiveImpactFetcher impact={impact} onSnapshot={setSnapshot} />
        </Suspense>
      ) : null}
    </>
  );
}
