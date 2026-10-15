"use client";

import {
  captureTikTokClickId,
  loadTikTokPixel,
  TikTokEvents,
  trackTikTokEvent,
} from "@juli/tiktok-events";
import { useEffect } from "react";

import { DEMO_URL, SIGNUP_URL } from "../lib/site";

const CONTENT_TYPE = "product";
const PAGE_CONTENT_NAME = "landing";

/**
 * Loads the TikTok Pixel and records the landing page's two conversions.
 * Renders nothing; `CookieConsent` mounts it only once the visitor has accepted
 * analytics cookies.
 *
 * `Pageview` is not here — the base pixel code fires it when it loads.
 */
export function TikTokTracking() {
  useEffect(() => {
    // Idempotent, and first: the events below queue on the `ttq` stub it installs.
    loadTikTokPixel();
    // Before the first event, so it carries the click that produced it. The
    // `ttclid` parameter is on the ad landing URL and nowhere else.
    captureTikTokClickId();

    trackTikTokEvent(TikTokEvents.viewContent, {
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
    // The free-trial CTAs go to the internal sign-up page (`SIGNUP_URL`,
    // "/dang-ky", built by P33-F). They keep the StartDemo event they had when
    // they pointed at the Demo's sign-in, so Events Manager stays continuous;
    // the form's own submit is P33-F's to track.
    const signup = new URL(SIGNUP_URL, window.location.href);

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

      const isSignup =
        destination.host === signup.host && destination.pathname === signup.pathname;
      if (destination.host !== demoHost && !isSignup) {
        return;
      }

      trackTikTokEvent(TikTokEvents.startDemo, {
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
