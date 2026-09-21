"use client";

import {
  captureTikTokClickId,
  TIKTOK_EVENTS,
  trackTikTokEvent,
} from "@juli/tiktok-events";
import { useEffect } from "react";

import { DEMO_URL } from "../lib/site";

const CONTENT_TYPE = "product";
const PAGE_CONTENT_NAME = "landing";

/**
 * The landing page's two conversions. Renders nothing; mount once in the root
 * layout.
 *
 * `Pageview` is not here — the base pixel code fires it in the initial HTML,
 * before this component hydrates.
 */
export function TikTokTracking() {
  useEffect(() => {
    // Before the first event, so it carries the click that produced it. The
    // `ttclid` parameter is on the ad landing URL and nowhere else.
    captureTikTokClickId();

    trackTikTokEvent(TIKTOK_EVENTS.viewContent, {
      content_name: PAGE_CONTENT_NAME,
      content_type: CONTENT_TYPE,
    });
  }, []);

  useEffect(() => {
    // One delegated listener rather than an onClick on each CTA. There are
    // five demo CTAs plus a footer link, all of them server components today;
    // adding a handler to each would turn the whole marketing page into client
    // components to record one event, and would silently miss the next CTA
    // somebody adds. `DEMO_URL` stays the single source of truth for what "the
    // demo" is, exactly as it already is for the hrefs themselves.
    const demoHost = new URL(DEMO_URL, window.location.href).host;

    function handleClick(event: MouseEvent) {
      if (!(event.target instanceof Element)) {
        return;
      }

      const anchor = event.target.closest("a[href]");
      const href = anchor?.getAttribute("href");

      if (!anchor || !href) {
        return;
      }

      let destination: URL;
      try {
        destination = new URL(href, window.location.href);
      } catch {
        return;
      }

      if (destination.host !== demoHost) {
        return;
      }

      trackTikTokEvent(TIKTOK_EVENTS.startDemo, {
        // Which CTA converted. The testids already distinguish them, so this
        // costs nothing and turns one number in Events Manager into six.
        content_name: anchor.getAttribute("data-testid") ?? "footer-demo-link",
        content_type: CONTENT_TYPE,
      });
    }

    // Capture phase: a handler that calls stopPropagation would otherwise hide
    // the click from us.
    document.addEventListener("click", handleClick, true);

    return () => document.removeEventListener("click", handleClick, true);
  }, []);

  return null;
}
