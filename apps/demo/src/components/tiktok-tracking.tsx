"use client";

import {
  captureTikTokClickId,
  hasTikTokAdReferral,
  loadTikTokPixel,
  trackTikTokPageView,
} from "@juli/tiktok-events";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * The Demo's TikTok channel, loaded only for a visitor who arrived from a
 * TikTok ad. Renders nothing; mount once in the root layout.
 *
 * WHY GATED, when `apps/landing` loads the pixel for everyone. The Demo's
 * anonymous replay carries a guarantee the marketing site does not: entering
 * and browsing it issues no request that leaves the origin
 * (`e2e/exit-gate/locale-and-assistance.spec.ts`, guarded in turn by
 * `tests/unit/test_phase_2_6_demo_exit_gate.py`). Loading the pixel for
 * everyone would quietly retire that. Gating on the ad click id keeps it
 * intact for every organic and replay visitor, and costs nothing that
 * attribution needs — the visitor an ad sent is the only one TikTok is
 * measuring. Owner decision, 2026-09-21.
 *
 * The consequence, stated so it is not discovered later: no retargeting or
 * lookalike audience is built from organic Demo visitors, because TikTok never
 * sees them.
 *
 * Loaded at runtime rather than rendered as `TikTokPixel`, because whether
 * this visitor came from an ad lives in their own browser storage and the
 * server cannot know it.
 *
 * `ViewContent` is deliberately not sent here. It marks the marketing page's
 * content being read (`apps/landing`); firing it on every screen of an
 * application would make an optimisation signal out of ordinary navigation.
 */
export function TikTokTracking() {
  const pathname = usePathname();
  // The path the last pageview was recorded for. Starts null so the first
  // effect run only records where we began, rather than double-counting the
  // pageview the base code sends as it loads. Comparing paths (rather than a
  // has-mounted flag) also makes this idempotent under React's development
  // double-invocation of effects.
  const trackedPath = useRef<string | null>(null);

  useEffect(() => {
    // An ad can land directly on the Demo, so capture first: the `ttclid` is
    // on the landing URL and nowhere else.
    captureTikTokClickId();

    if (hasTikTokAdReferral()) {
      loadTikTokPixel();
    }
  }, []);

  useEffect(() => {
    if (!hasTikTokAdReferral()) {
      return;
    }

    if (trackedPath.current === null) {
      trackedPath.current = pathname;
      return;
    }

    if (trackedPath.current === pathname) {
      return;
    }

    trackedPath.current = pathname;
    trackTikTokPageView();
  }, [pathname]);

  return null;
}
