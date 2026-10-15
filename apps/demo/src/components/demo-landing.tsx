"use client";

import { useEffect, useState } from "react";

import { Button } from "@juli/ui";

import { readEntryMode, writeEntryMode } from "../lib/entry-mode";
import {
  EMAIL_SIGN_IN_LABEL,
  EMAIL_SIGN_IN_UNAVAILABLE_COPY,
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY,
  buildGoogleAuthorizeUrl,
} from "../lib/supabase-auth";
import {
  TRIAL_SIGNUP_BODY,
  TRIAL_SIGNUP_EXISTING_NOTE,
  TRIAL_SIGNUP_EYEBROW,
  TRIAL_SIGNUP_HEADING,
  isTrialSignupSearch,
} from "../lib/trial-signup-copy";
import { EmailSignIn } from "./email-sign-in";
import { LegalConsentNote } from "./legal-consent-note";
import { SampleHome } from "./home/sample-home";

/**
 * The landing's two deliberately asymmetric doors (ADR-094, PUI-DESIGN §1).
 * "Dùng thử Demo" flips local, session-scoped state only — it calls nothing.
 * The sign-in door holds Google and, since AC-9.1, "Đăng nhập bằng email"
 * (a disclosure revealing `EmailSignIn`; email OTP code or magic link).
 * "Đăng nhập với Google" is a real, full-page link to Supabase Auth; its href
 * is resolved on mount (never during SSR, so client and server agree on the
 * first paint) and is `null` — an honest disabled state, not a broken link —
 * when Supabase env is not configured in this build.
 *
 * `/?entry=door` (issue #1907) is the explicit escape from the
 * `hasEnteredReplay` short-circuit below — without it, once a visitor picked
 * "Dùng thử Demo", the Google door became unreachable for the rest of the
 * tab session by any navigation back to `/`. This does not remove the
 * short-circuit: a bare `/` visit with replay stored still goes straight to
 * the sample Home (`SampleHome`, AC-8.5), unchanged.
 *
 * The param is read from `window.location.search` inside the same deferred
 * client-only read as the entry mode, NOT via `useSearchParams` — that hook
 * forces a Suspense boundary around the page during `next build`
 * (missing-suspense-with-csr-bailout) and would replace the landing's
 * statically prerendered HTML with a fallback shell. The escape is for
 * fresh navigations (a typed URL or the header's full-page links); a
 * same-page client-side query change would not re-run the mount effect,
 * and no such internal link exists.
 *
 * `/?dang-ky=dung-thu` (D43 additions, owner 2026-10-15) is app-juli.com's
 * "Dùng thử miễn phí 3 tháng" CTA: it also forces the doors, and the sign-in
 * door reads as the trial sign-up (`lib/trial-signup-copy.ts`). The buttons are
 * the same, so an existing seller still signs in there.
 */
export function DemoLanding() {
  const [forceDoorEntry, setForceDoorEntry] = useState(false);
  const [trialSignup, setTrialSignup] = useState(false);
  const [hasEnteredReplay, setHasEnteredReplay] = useState(false);
  const [googleHref, setGoogleHref] = useState<string | null | undefined>(
    undefined,
  );
  const [emailOpen, setEmailOpen] = useState(false);

  // Deferred via setTimeout(0) rather than calling the setter synchronously
  // in the effect body — the same pattern `demo-state.tsx` already uses for
  // its own browser-storage read (`react-hooks/set-state-in-effect`).
  useEffect(() => {
    const timer = window.setTimeout(() => {
      // Both reads land in the same deferred callback (one React batch), so
      // the launcher-vs-doors decision below is made once — never a flash
      // of the sample Home before the escape param is honoured.
      const trial = isTrialSignupSearch(window.location.search);
      setTrialSignup(trial);
      setForceDoorEntry(
        trial || new URLSearchParams(window.location.search).get("entry") === "door",
      );
      if (readEntryMode() === "replay") {
        setHasEnteredReplay(true);
      }
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setGoogleHref(
        buildGoogleAuthorizeUrl(`${window.location.origin}/auth/callback`),
      );
    }, 0);

    return () => window.clearTimeout(timer);
  }, []);

  if (hasEnteredReplay && !forceDoorEntry) {
    return <SampleHome />;
  }

  const handleEnterReplay = () => {
    writeEntryMode("replay");
    setHasEnteredReplay(true);
  };

  const googleConfigured = googleHref !== null && googleHref !== undefined;
  // Distinct from "not yet resolved" (`googleHref === undefined`, the
  // transient pre-effect state that also renders the disabled branch to
  // match SSR) -- the visible unavailable copy below only appears once the
  // door's fate is actually decided, so a build that IS configured never
  // flashes "chưa sẵn sàng" for one frame before the real link appears.
  const googleUnavailable = googleHref === null;

  return (
    <section aria-labelledby="landing-title" className="demo-landing">
      <p className="demo-kicker">Chào mừng đến với Juli</p>
      <h1 className="demo-title" id="landing-title">
        Chọn cách bạn muốn bắt đầu
      </h1>

      <div className="demo-landing__doors" role="group" aria-label="Chọn lối vào">
        <article className="demo-landing__door">
          <p className="demo-landing__door-eyebrow">Xem thử, không cần tài khoản</p>
          <h2>Dùng thử Demo</h2>
          <p>
            Đây là bản minh họa dựng từ dữ liệu mẫu đã ghi lại sẵn — không
            phải dữ liệu shop thật của bạn, và không tạo tài khoản nào.
          </p>
          <Button onClick={handleEnterReplay} type="button">
            Dùng thử Demo
          </Button>
        </article>

        <article className="demo-landing__door demo-landing__door--google">
          {trialSignup ? (
            <>
              <p className="demo-landing__door-eyebrow">{TRIAL_SIGNUP_EYEBROW}</p>
              <h2>{TRIAL_SIGNUP_HEADING}</h2>
              <p>{TRIAL_SIGNUP_BODY}</p>
              <p className="demo-landing__trial-existing">{TRIAL_SIGNUP_EXISTING_NOTE}</p>
            </>
          ) : (
            <>
              <p className="demo-landing__door-eyebrow">Tài khoản thật của bạn</p>
              <h2>Đăng nhập</h2>
              <p>
                Tạo tài khoản Juli thật bằng Google hoặc email, sau đó đến màn
                hình Kết nối TikTok Shop.
              </p>
            </>
          )}
          {googleConfigured ? (
            <a className="demo-landing__google-link juli-btn juli-btn--secondary juli-btn--default" href={googleHref}>
              Đăng nhập với Google
            </a>
          ) : (
            <>
              <span
                aria-disabled="true"
                className="demo-landing__google-link demo-landing__google-link--disabled juli-btn juli-btn--secondary juli-btn--default"
                role="link"
                aria-label="Đăng nhập với Google — chưa cấu hình trong môi trường này"
              >
                Đăng nhập với Google
              </span>
              {googleUnavailable ? (
                // dictionary.md `auth.google.unavailable` (issue #1905) --
                // the disabled state's explanation as VISIBLE copy, not
                // only the aria-label above.
                <p className="demo-landing__google-unavailable" role="status">
                  {GOOGLE_SIGN_IN_UNAVAILABLE_COPY}
                </p>
              ) : null}
            </>
          )}
          {/* AC-9.1: the email door sits beside Google and shares its
              configured/unconfigured fate (same two NEXT_PUBLIC_SUPABASE_*
              values), so "chưa sẵn sàng" is said once, above. */}
          <p aria-hidden="true" className="demo-landing__or">hoặc</p>
          {googleConfigured ? (
            <>
              <Button
                aria-controls="landing-email-sign-in"
                aria-expanded={emailOpen}
                onClick={() => setEmailOpen((open) => !open)}
                type="button"
                variant="secondary"
              >
                {EMAIL_SIGN_IN_LABEL}
              </Button>
              <div hidden={!emailOpen} id="landing-email-sign-in">
                {emailOpen ? <EmailSignIn autoFocus /> : null}
              </div>
              {/* P32-A: team-created partner trial accounts sign in with a password on /auth/email. */}
              <a className="demo-landing__partner" href="/auth/email#doi-tac">
                Tài khoản đối tác (đăng nhập bằng mật khẩu)
              </a>
            </>
          ) : (
            <>
              <Button disabled type="button" variant="secondary">
                {EMAIL_SIGN_IN_LABEL}
              </Button>
              {googleUnavailable ? (
                <p className="demo-landing__google-unavailable">{EMAIL_SIGN_IN_UNAVAILABLE_COPY}</p>
              ) : null}
            </>
          )}
          <LegalConsentNote />
        </article>
      </div>
    </section>
  );
}
