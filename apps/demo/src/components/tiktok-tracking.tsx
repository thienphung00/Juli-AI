"use client";

import { captureTikTokClickId, trackTikTokPageView } from "@juli/tiktok-events";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

/**
 * Pageviews for client-side navigation. Renders nothing; mount once in the
 * root layout.
 *
 * The base pixel code fires a pageview from the initial HTML. Every navigation
 * after that is a React route change with no document load, so nothing else
 * would fire one — the whole demo would report as a single page.
 *
 * `ViewContent` is deliberately not sent here. It marks the marketing page's
 * content being read (`apps/landing`); firing it on every screen of an
 * application would make an optimisation signal out of ordinary navigation.
 */
export function TikTokTracking() {
  const pathname = usePathname();
  // The path the last pageview was recorded for. Starts null so the first
  // effect run only records where we began, rather than double-counting the
  // pageview the base code already sent. Comparing paths (rather than a
  // has-mounted flag) also makes this idempotent under React's development
  // double-invocation of effects.
  const trackedPath = useRef<string | null>(null);

  useEffect(() => {
    // An ad can land directly on the Demo, so the click id has to be captured
    // here too — it is on the landing URL and nowhere else.
    captureTikTokClickId();
  }, []);

  useEffect(() => {
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
