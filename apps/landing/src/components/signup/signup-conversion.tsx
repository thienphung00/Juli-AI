"use client";

import { useEffect } from "react";

import { readConsent } from "../../lib/consent";
import { SIGNUP_DONE_FLAG } from "./signup-content";

export const SIGNUP_CONVERSION = {
  content_name: "trial_signup",
  content_type: "product",
} as const;

/**
 * The thank-you page's TikTok "CompleteRegistration" — once per real sign-up
 * (the form sets {@link SIGNUP_DONE_FLAG} on success; a reload or a direct
 * visit finds no flag and records nothing), and only behind the analytics
 * consent the rest of the site uses (`lib/consent`, Nghị định 13/2023): no
 * choice or a refusal means the pixel package is not even downloaded.
 */
export function SignupConversion() {
  useEffect(() => {
    let flagged = false;
    try {
      flagged = window.sessionStorage.getItem(SIGNUP_DONE_FLAG) !== null;
      window.sessionStorage.removeItem(SIGNUP_DONE_FLAG);
    } catch {
      flagged = false;
    }
    if (!flagged || readConsent() !== "granted") return;
    void import("@juli/tiktok-events").then(
      ({ loadTikTokPixel, trackTikTokEvent, TikTokEvents }) => {
        loadTikTokPixel(); // idempotent; CookieConsent's TikTokTracking calls it too
        trackTikTokEvent(TikTokEvents.completeRegistration, SIGNUP_CONVERSION);
      },
      () => undefined,
    );
  }, []);
  return null;
}
