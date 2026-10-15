"use client";

import { TIKTOK_PIXEL_SCRIPT_ID } from "@juli/tiktok-events/pixel-id";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";

import {
  clearTikTokCookies,
  type ConsentChoice,
  OPEN_CONSENT_EVENT,
  readConsent,
  subscribeConsent,
  writeConsent,
} from "../lib/consent";
import { buttonClassName } from "./ui";

/**
 * The pixel loader is its own chunk, fetched only after consent: a visitor who
 * never accepts (and every first visit) downloads none of it (D43.4 unused JS).
 */
const TikTokTracking = dynamic(
  () => import("./tiktok-tracking").then((module) => module.TikTokTracking),
  { ssr: false },
);

/** Distinguishes "not hydrated yet" from "no choice made" (`null`). */
const NOT_HYDRATED = "not-hydrated" as const;

/**
 * Consent gate for all analytics: `TikTokTracking` — which loads the TikTok
 * Pixel and feeds it and the Events API relay — mounts only after the visitor
 * accepts.
 * Until then nothing is loaded and no event leaves the browser.
 *
 * The server renders nothing (it cannot know the choice), so a returning
 * visitor never sees the banner flash.
 */
export function CookieConsent() {
  const choice = useSyncExternalStore<ConsentChoice | null | typeof NOT_HYDRATED>(
    subscribeConsent,
    readConsent,
    () => NOT_HYDRATED,
  );
  const [reopened, setReopened] = useState(false);

  useEffect(() => {
    function reopen() {
      setReopened(true);
    }
    window.addEventListener(OPEN_CONSENT_EVENT, reopen);
    return () => window.removeEventListener(OPEN_CONSENT_EVENT, reopen);
  }, []);

  function decide(next: ConsentChoice) {
    setReopened(false);
    const pixelWasLoaded = document.getElementById(TIKTOK_PIXEL_SCRIPT_ID) !== null;
    writeConsent(next);
    if (next === "denied" && pixelWasLoaded) {
      // A loaded pixel cannot be unloaded; drop its cookies and start over.
      clearTikTokCookies();
      window.location.reload();
    }
  }

  if (choice === NOT_HYDRATED) {
    return null;
  }

  return (
    <>
      {choice === "granted" ? <TikTokTracking /> : null}
      {choice === null || reopened ? (
        <section
          aria-label="Cài đặt cookie"
          aria-live="polite"
          className="lp-consent"
          data-testid="cookie-consent"
        >
          <p className="lp-consent__text">
            Juli dùng cookie và TikTok Pixel để đo lường hiệu quả quảng cáo. Chúng tôi chỉ
            bật khi bạn đồng ý; website vẫn hoạt động đầy đủ nếu bạn từ chối. Xem{" "}
            <Link className="lp-consent__link" href="/privacy">
              Chính sách bảo mật
            </Link>
            .
          </p>
          <div className="lp-consent__actions">
            <button
              className={buttonClassName({ variant: "secondary", size: "md" })}
              onClick={() => decide("denied")}
              type="button"
            >
              Từ chối
            </button>
            <button
              className={buttonClassName({ variant: "primary", size: "md" })}
              onClick={() => decide("granted")}
              type="button"
            >
              Đồng ý
            </button>
          </div>
        </section>
      ) : null}
    </>
  );
}
