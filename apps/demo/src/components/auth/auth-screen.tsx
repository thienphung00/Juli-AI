"use client";

import { useEffect, useId, useRef, useState, type FormEvent, type MouseEvent, type ReactNode } from "react";

import {
  AUTH_DIVIDER,
  AUTH_EMAIL_LABEL,
  AUTH_EMAIL_PLACEHOLDER,
  AUTH_EMAIL_SEND_LABEL,
  AUTH_EMAIL_SENDING,
  AUTH_FOOTER_COPYRIGHT,
  AUTH_FOOTER_PRIVACY,
  AUTH_FOOTER_TERMS,
  AUTH_GOOGLE_LABEL,
  AUTH_HEADING,
  AUTH_HOME_URL,
  AUTH_LOGO_LABEL,
  AUTH_OTP_CHANGE_EMAIL,
  AUTH_OTP_CONFIRM,
  AUTH_OTP_CONFIRMING,
  AUTH_OTP_HEADING,
  AUTH_OTP_LEGEND,
  AUTH_OTP_NEW_CODE,
  AUTH_OTP_RESEND,
  AUTH_OTP_SENT_PREFIX,
  AUTH_OTP_SENT_SUFFIX,
  AUTH_PANEL_CAPTION,
  AUTH_PANEL_EYEBROW,
  AUTH_PANEL_HEADLINE,
  AUTH_PANEL_IMAGE_ALT,
  AUTH_PANEL_LABEL,
  AUTH_PANEL_PROOF,
  AUTH_PARTNER_BACK,
  AUTH_PARTNER_EYEBROW,
  AUTH_PARTNER_HEADING,
  AUTH_PARTNER_HREF,
  AUTH_PARTNER_LINK,
  AUTH_PARTNER_SUB,
  AUTH_PARTNER_TOP_ACTION,
  AUTH_PARTNER_TOP_LEAD,
  AUTH_SAMPLE_ENTRY,
  AUTH_SUB,
  AUTH_SWITCH_LINK,
  AUTH_SWITCH_TEXT,
  authEmailCooldownLabel,
  authOtpResendCountdown,
  maskEmail,
} from "../../lib/auth-screen-copy";
import {
  EMAIL_SIGN_IN_LABEL,
  EMAIL_SIGN_IN_UNAVAILABLE_COPY,
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY,
  buildGoogleAuthorizeUrl,
  type AuthSession,
} from "../../lib/supabase-auth";
import {
  TRIAL_SIGNUP_BODY,
  TRIAL_SIGNUP_CODE_LEGEND,
  TRIAL_SIGNUP_CONFIRM_LABEL,
  TRIAL_SIGNUP_EMAIL_LABEL,
  TRIAL_SIGNUP_EYEBROW,
  TRIAL_SIGNUP_GOOGLE_LABEL,
  TRIAL_SIGNUP_HEADING,
  TRIAL_SIGNUP_PARAM,
  TRIAL_SIGNUP_SWITCH_LINK,
  TRIAL_SIGNUP_SWITCH_TEXT,
} from "../../lib/trial-signup-copy";
import { LegalConsentNote, PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL } from "../legal-consent-note";
import { AuthAlert, AuthSpinner } from "./auth-alert";
import { OtpCodeInput } from "./otp-code-input";
import { defaultOnSignedIn, useEmailOtp } from "./use-email-otp";

/**
 * The demo's sign-in / sign-up screen (P34-F, D44.5; spec
 * `fasttrack/design/p34/Auth.dc.html` + `AuthMobile.dc.html`). Rendered with
 * NO app shell (`DemoShell` steps aside): logo top-left, one 400 px column,
 * footer links, and on desktop a right panel with a product shot.
 *
 * Hierarchy: "Tiếp tục với Google" is the only filled button; the email code
 * is second ("hoặc dùng email", an outline "Gửi mã đăng nhập"); the sample
 * demo is a text link under the column; the partner view is reached from a
 * quiet pill at the top of the entry column ("Đối tác thẩm định? Đăng nhập
 * bằng tài khoản đối tác →", D47.6, so a reviewer sees it without scrolling)
 * and from the footer link "Tài khoản đối tác". `trial` (`?dang-ky=dung-thu`)
 * changes copy only.
 *
 * Flows are the pre-P34 ones, unchanged: Google is a real full-page link to
 * Supabase Auth resolved on mount (never during SSR; an honest disabled state
 * when Supabase env is absent), the email code is `useEmailOtp`, the partner
 * password form is whatever `renderPartner` returns (only `/auth/email`
 * passes it — see `partner-sign-in.tsx` for why the landing must not).
 */

export type AuthView = "entry" | "partner";

export interface AuthScreenProps {
  readonly trial: boolean;
  readonly onTrialChange: (trial: boolean) => void;
  /** "Xem thử với dữ liệu mẫu": enters the existing sample demo. */
  readonly onEnterSample: () => void;
  /** The partner password form. Absent → the top and footer links go to `/auth/email#doi-tac`. */
  readonly renderPartner?: () => ReactNode;
  readonly initialView?: AuthView;
  /** Focus the email field on mount (`/auth/email`, the avatar menu's "Đăng nhập bằng email"). */
  readonly focusEmail?: boolean;
  readonly onSignedIn?: (session: AuthSession) => void;
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" className="auth-btn__icon" height="18" viewBox="0 0 48 48" width="18">
      <path
        d="M44.5 20H24v8.5h11.8C34.7 33.9 30.1 37 24 37c-7.2 0-13-5.8-13-13s5.8-13 13-13c3.1 0 5.9 1.1 8.1 2.9l6.4-6.4C34.6 4.1 29.6 2 24 2 11.8 2 2 11.8 2 24s9.8 22 22 22c11 0 21-8 21-22 0-1.3-.2-2.7-.5-4z"
        fill="currentColor"
      />
    </svg>
  );
}

export function AuthScreen({
  trial,
  onTrialChange,
  onEnterSample,
  renderPartner,
  initialView = "entry",
  focusEmail = false,
  onSignedIn = defaultOnSignedIn,
}: AuthScreenProps) {
  const baseId = useId();
  const flow = useEmailOtp(onSignedIn);
  const [view, setView] = useState<AuthView>(renderPartner ? initialView : "entry");
  const [googleHref, setGoogleHref] = useState<string | null | undefined>(undefined);
  const [codeEntry, setCodeEntry] = useState({ attempt: 0, code: "" });
  const emailRef = useRef<HTMLInputElement | null>(null);
  const partnerHeadingRef = useRef<HTMLHeadingElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setGoogleHref(buildGoogleAuthorizeUrl(`${window.location.origin}/auth/callback`));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const screen = view === "partner" ? "partner" : flow.step === "code" ? "otp" : "entry";

  // Move focus with the view (the OTP view focuses its first box itself).
  const previousScreen = useRef(screen);
  useEffect(() => {
    if (previousScreen.current === screen) return;
    previousScreen.current = screen;
    if (screen === "entry") emailRef.current?.focus();
    if (screen === "partner") partnerHeadingRef.current?.focus();
  }, [screen]);

  // Distinct from "not yet resolved" (`undefined`, which also renders the
  // disabled branch so SSR and the first client paint agree): the visible
  // "chưa sẵn sàng" copy appears only once the fate is actually decided.
  const configured = typeof googleHref === "string";
  const unavailable = googleHref === null;

  const googleLabel = trial ? TRIAL_SIGNUP_GOOGLE_LABEL : AUTH_GOOGLE_LABEL;
  const sendLabel = trial ? TRIAL_SIGNUP_EMAIL_LABEL : AUTH_EMAIL_SEND_LABEL;
  const code = codeEntry.attempt === flow.attempt ? codeEntry.code : "";

  const toggleTrial = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    const next = !trial;
    const url = new URL(window.location.href);
    url.hash = "";
    if (next) {
      url.searchParams.delete("entry");
      url.searchParams.set(TRIAL_SIGNUP_PARAM.name, TRIAL_SIGNUP_PARAM.value);
    } else {
      url.searchParams.delete(TRIAL_SIGNUP_PARAM.name);
      // On `/` a reload must keep showing this screen even with the sample stored.
      if (url.pathname === "/") url.searchParams.set("entry", "door");
    }
    window.history.replaceState(window.history.state, "", url);
    flow.clearError();
    onTrialChange(next);
  };

  const openPartner = (event: MouseEvent<HTMLAnchorElement>) => {
    if (!renderPartner) return; // a real link to /auth/email#doi-tac
    event.preventDefault();
    window.history.replaceState(window.history.state, "", "#doi-tac");
    setView("partner");
  };

  // The top pill and the footer link: same target, same in-page behaviour.
  const partnerHref = renderPartner ? "#doi-tac" : AUTH_PARTNER_HREF;

  const closePartner = () => {
    const url = new URL(window.location.href);
    url.hash = "";
    url.searchParams.delete("doi-tac");
    window.history.replaceState(window.history.state, "", url);
    setView("entry");
  };

  const onEmailSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!flow.pending && flow.cooldown === 0) void flow.sendCode();
  };

  const onCodeSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!flow.pending) void flow.verify(code);
  };

  const errorId = `${baseId}-error`;
  const emailId = `${baseId}-email`;

  let column: ReactNode;

  if (screen === "partner" && renderPartner) {
    column = (
      <section aria-labelledby={`${baseId}-partner-title`} className="auth-view" id="doi-tac">
        <div className="auth-head">
          <p className="auth-eyebrow">{AUTH_PARTNER_EYEBROW}</p>
          <h1 className="auth-title" id={`${baseId}-partner-title`} ref={partnerHeadingRef} tabIndex={-1}>
            {AUTH_PARTNER_HEADING}
          </h1>
          <p className="auth-sub">{AUTH_PARTNER_SUB}</p>
        </div>
        {renderPartner()}
        <button className="auth-link auth-link--strong auth-link--start" onClick={closePartner} type="button">
          {AUTH_PARTNER_BACK}
        </button>
      </section>
    );
  } else if (screen === "otp") {
    const busy = flow.pending;
    column = (
      <section aria-labelledby={`${baseId}-otp-title`} className="auth-view">
        <div className="auth-head">
          {trial ? <p className="auth-eyebrow">{TRIAL_SIGNUP_EYEBROW}</p> : null}
          <h1 className="auth-title" id={`${baseId}-otp-title`}>
            {AUTH_OTP_HEADING}
          </h1>
          <p className="auth-sub">
            {AUTH_OTP_SENT_PREFIX} <strong className="auth-strong">{maskEmail(flow.email)}</strong>
            {AUTH_OTP_SENT_SUFFIX}
          </p>
        </div>
        <form aria-label={AUTH_OTP_HEADING} className="auth-form auth-form--loose" noValidate onSubmit={onCodeSubmit}>
          <OtpCodeInput
            autoFocus
            describedBy={flow.error ? errorId : undefined}
            disabled={busy}
            invalid={flow.error !== null}
            key={flow.attempt}
            legend={trial ? TRIAL_SIGNUP_CODE_LEGEND : AUTH_OTP_LEGEND}
            onChange={(next) => {
              setCodeEntry({ attempt: flow.attempt, code: next });
              if (flow.error) flow.clearError();
            }}
            onComplete={(full) => {
              setCodeEntry({ attempt: flow.attempt, code: full });
              if (!flow.pending) void flow.verify(full);
            }}
          />
          {flow.error ? (
            <AuthAlert id={errorId}>
              <p>{flow.error.message}</p>
              {flow.error.kind === "invalid_code" && flow.cooldown === 0 ? (
                <button
                  className="auth-link auth-link--strong"
                  disabled={busy}
                  onClick={() => void flow.sendCode()}
                  type="button"
                >
                  {AUTH_OTP_NEW_CODE}
                </button>
              ) : null}
            </AuthAlert>
          ) : null}
          {flow.notice ? (
            <p className="auth-notice" role="status">
              {flow.notice}
            </p>
          ) : null}
          <button aria-busy={busy || undefined} className="auth-btn auth-btn--ink" disabled={busy} type="submit">
            {busy ? <AuthSpinner /> : null}
            {busy ? AUTH_OTP_CONFIRMING : trial ? TRIAL_SIGNUP_CONFIRM_LABEL : AUTH_OTP_CONFIRM}
          </button>
        </form>
        <div className="auth-row">
          <button className="auth-link auth-link--strong" disabled={busy} onClick={flow.changeEmail} type="button">
            {AUTH_OTP_CHANGE_EMAIL}
          </button>
          <button
            className="auth-link auth-link--quiet"
            disabled={busy || flow.cooldown > 0}
            onClick={() => void flow.sendCode()}
            type="button"
          >
            {flow.cooldown > 0 ? authOtpResendCountdown(flow.cooldown) : AUTH_OTP_RESEND}
          </button>
        </div>
      </section>
    );
  } else {
    const sending = flow.pending;
    const emailError = flow.error;
    column = (
      <section aria-labelledby={`${baseId}-title`} className="auth-view">
        {/* D47.6: above the heading, secondary to Google (outline pill, no fill). */}
        <a className="auth-partner-top" data-auth-partner-top="" href={partnerHref} onClick={openPartner}>
          <span className="auth-partner-top__lead">{AUTH_PARTNER_TOP_LEAD}</span>{" "}
          <span className="auth-partner-top__action">
            {AUTH_PARTNER_TOP_ACTION}
            <span aria-hidden="true"> →</span>
          </span>
        </a>

        <div className="auth-head">
          <h1 className="auth-title" id={`${baseId}-title`}>
            {trial ? TRIAL_SIGNUP_HEADING : AUTH_HEADING}
          </h1>
          <p className="auth-sub">{trial ? TRIAL_SIGNUP_BODY : AUTH_SUB}</p>
        </div>

        {configured ? (
          <a className="auth-btn auth-btn--ink" data-auth-primary="" href={googleHref}>
            <GoogleMark />
            {googleLabel}
          </a>
        ) : (
          <div className="auth-stack">
            <span
              aria-disabled="true"
              aria-label={`${googleLabel}: chưa cấu hình trong môi trường này`}
              className="auth-btn auth-btn--ink auth-btn--disabled"
              data-auth-primary=""
              role="link"
            >
              <GoogleMark />
              {googleLabel}
            </span>
            {unavailable ? (
              // dictionary.md `auth.google.unavailable` (issue #1905): the
              // disabled state's explanation as VISIBLE copy.
              <p className="auth-note" role="status">
                {GOOGLE_SIGN_IN_UNAVAILABLE_COPY}
              </p>
            ) : null}
          </div>
        )}

        <div className="auth-divider">
          <span aria-hidden="true" className="auth-divider__rule" />
          <span>{AUTH_DIVIDER}</span>
          <span aria-hidden="true" className="auth-divider__rule" />
        </div>

        <form aria-label={EMAIL_SIGN_IN_LABEL} className="auth-form" noValidate onSubmit={onEmailSubmit}>
          <label className="auth-label" htmlFor={emailId}>
            {AUTH_EMAIL_LABEL}
          </label>
          <input
            aria-describedby={emailError ? errorId : undefined}
            aria-invalid={emailError?.kind === "invalid_email" ? true : undefined}
            autoComplete="email"
            // `/auth/email` is reached by choosing "Đăng nhập bằng email".
            autoFocus={focusEmail}
            className="auth-input"
            disabled={unavailable}
            id={emailId}
            inputMode="email"
            name="email"
            onChange={(event) => flow.setEmail(event.target.value)}
            placeholder={AUTH_EMAIL_PLACEHOLDER}
            ref={emailRef}
            type="email"
            value={flow.email}
          />
          {emailError ? <AuthAlert id={errorId}>{emailError.message}</AuthAlert> : null}
          <button
            aria-busy={sending || undefined}
            className="auth-btn auth-btn--outline"
            disabled={!configured || sending || flow.cooldown > 0}
            type="submit"
          >
            {sending ? <AuthSpinner /> : null}
            {sending ? AUTH_EMAIL_SENDING : flow.cooldown > 0 ? authEmailCooldownLabel(flow.cooldown) : sendLabel}
          </button>
          {unavailable ? <p className="auth-note">{EMAIL_SIGN_IN_UNAVAILABLE_COPY}</p> : null}
        </form>

        <LegalConsentNote />

        <div className="auth-after">
          <button className="auth-link auth-link--strong auth-link--start" onClick={onEnterSample} type="button">
            {AUTH_SAMPLE_ENTRY}
          </button>
          <p className="auth-switch">
            {trial ? TRIAL_SIGNUP_SWITCH_TEXT : AUTH_SWITCH_TEXT}{" "}
            <a
              className="auth-link auth-link--strong"
              href={trial ? "?entry=door" : `?${TRIAL_SIGNUP_PARAM.name}=${TRIAL_SIGNUP_PARAM.value}`}
              onClick={toggleTrial}
            >
              {trial ? TRIAL_SIGNUP_SWITCH_LINK : AUTH_SWITCH_LINK}
            </a>
          </p>
        </div>
      </section>
    );
  }

  return (
    <div className="auth-screen">
      <div className="auth-screen__main">
        <header className="auth-screen__top">
          <a aria-label={AUTH_LOGO_LABEL} className="auth-logo" href={AUTH_HOME_URL}>
            {/* A 64 px copy of packages/brand/assets/bird-glyph.png. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img alt="" className="auth-logo__glyph" height={26} src="/auth/bird-glyph-64.png" width={30} />
            <span className="auth-logo__word">Juli AI</span>
          </a>
        </header>

        <main className="auth-screen__center">
          <div className="auth-column">{column}</div>
        </main>

        <footer className="auth-footer">
          <nav aria-label="Liên kết phụ" className="auth-footer__links">
            <a className="auth-footer__link" href={partnerHref} onClick={openPartner}>
              {AUTH_PARTNER_LINK}
            </a>
            <a className="auth-footer__link" href={TERMS_OF_SERVICE_URL}>
              {AUTH_FOOTER_TERMS}
            </a>
            <a className="auth-footer__link" href={PRIVACY_POLICY_URL}>
              {AUTH_FOOTER_PRIVACY}
            </a>
          </nav>
          <span className="auth-footer__copy">{AUTH_FOOTER_COPYRIGHT}</span>
        </footer>
      </div>

      <aside aria-label={AUTH_PANEL_LABEL} className="auth-panel">
        <div className="auth-panel__lead">
          <p className="auth-eyebrow">{AUTH_PANEL_EYEBROW}</p>
          <p className="auth-panel__headline">{AUTH_PANEL_HEADLINE}</p>
        </div>
        <figure className="auth-panel__shot">
          <picture>
            <source
              sizes="(min-width: 1024px) 560px, 1px"
              srcSet="/auth/cap-dx-the-v3-640.avif 640w, /auth/cap-dx-the-v3-1184.avif 1184w"
              type="image/avif"
            />
            <source
              sizes="(min-width: 1024px) 560px, 1px"
              srcSet="/auth/cap-dx-the-v3-640.webp 640w, /auth/cap-dx-the-v3-1184.webp 1184w"
              type="image/webp"
            />
            <img
              alt={AUTH_PANEL_IMAGE_ALT}
              className="auth-panel__img"
              decoding="async"
              height={868}
              loading="lazy"
              src="/auth/cap-dx-the-v3-640.webp"
              width={1184}
            />
          </picture>
          <figcaption className="auth-panel__caption">{AUTH_PANEL_CAPTION}</figcaption>
        </figure>
        <ul className="auth-panel__proof">
          {AUTH_PANEL_PROOF.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
