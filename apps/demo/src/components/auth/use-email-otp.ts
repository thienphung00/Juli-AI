"use client";

import { useCallback, useEffect, useState } from "react";

import { AUTH_OTP_INCOMPLETE, AUTH_OTP_SIGNED_IN } from "../../lib/auth-screen-copy";
import {
  EMAIL_OTP_ERROR_COPY,
  EMAIL_OTP_RESEND_COOLDOWN_SECONDS,
  isValidEmail,
  normaliseOtpCode,
  requestEmailOtp,
  storeAuthSession,
  verifyEmailOtp,
  type AuthSession,
  type EmailOtpErrorKind,
  type EmailOtpFailure,
} from "../../lib/supabase-auth";
import { reportTikTokRegistration } from "../../lib/tiktok-registration";

/**
 * Email sign-in (AC-9.1) as a state machine, without markup: email →
 * `POST /auth/v1/otp` → the 6-digit code → `POST /auth/v1/verify` → signed
 * in. The same email also carries a magic link to `/auth/callback`, handled
 * there. On success the session is stored exactly as the Google callback
 * stores it, then (by default) a FULL load to `/auth/connect-shop` — so the
 * shell's providers (which resolve the session once, on mount) see it.
 *
 * Behaviour is the pre-P34 `EmailSignIn`'s, unchanged: 60 s resend cooldown
 * (or the wait GoTrue names on a rate limit), fixed Vietnamese errors
 * (`EMAIL_OTP_ERROR_COPY`, never GoTrue's text), the code never echoed.
 * P34-F only split the markup out (`auth-screen.tsx`).
 */

export type EmailOtpStep = "email" | "code";

/** An error to show, with its kind so the view can add "Gửi mã mới" on a bad code. */
export interface EmailOtpError {
  readonly kind: EmailOtpErrorKind | "incomplete";
  readonly message: string;
}

export function defaultOnSignedIn(session: AuthSession) {
  // Same order as the Google callback: session first, the conversion report
  // fire-and-forget, so it can never cost the seller their sign-in.
  void reportTikTokRegistration(session.accessToken);
  window.location.assign("/auth/connect-shop");
}

export function useEmailOtp(onSignedIn: (session: AuthSession) => void = defaultOnSignedIn) {
  const [step, setStep] = useState<EmailOtpStep>("email");
  const [email, setEmailValue] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<EmailOtpError | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);
  /** Bumped after every failed verify so the code boxes clear and refocus. */
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const showFailure = useCallback((failure: EmailOtpFailure) => {
    setError({ kind: failure.error, message: EMAIL_OTP_ERROR_COPY[failure.error] });
    if (failure.error === "rate_limited") {
      setCooldown(failure.retryAfterSeconds ?? EMAIL_OTP_RESEND_COOLDOWN_SECONDS);
    }
  }, []);

  const setEmail = useCallback((value: string) => {
    setEmailValue(value);
    setError(null);
  }, []);

  const sendCode = useCallback(async () => {
    const trimmed = email.trim();
    if (!isValidEmail(trimmed)) {
      setError({ kind: "invalid_email", message: EMAIL_OTP_ERROR_COPY.invalid_email });
      return;
    }
    setPending(true);
    setError(null);
    setNotice(null);
    const result = await requestEmailOtp(trimmed, `${window.location.origin}/auth/callback`);
    setPending(false);
    if (!result.ok) {
      showFailure(result);
      return;
    }
    setEmailValue(trimmed);
    setStep("code");
    setAttempt((value) => value + 1);
    setCooldown(EMAIL_OTP_RESEND_COOLDOWN_SECONDS);
  }, [email, showFailure]);

  const verify = useCallback(
    async (raw: string) => {
      const digits = normaliseOtpCode(raw);
      if (digits.length < 6) {
        setError({ kind: "incomplete", message: AUTH_OTP_INCOMPLETE });
        return;
      }
      setPending(true);
      setError(null);
      const result = await verifyEmailOtp(email, digits);
      if (!result.ok) {
        setPending(false);
        setAttempt((value) => value + 1);
        showFailure(result);
        return;
      }
      storeAuthSession(result.session);
      setNotice(AUTH_OTP_SIGNED_IN);
      onSignedIn(result.session);
    },
    [email, onSignedIn, showFailure],
  );

  const changeEmail = useCallback(() => {
    setStep("email");
    setError(null);
    setNotice(null);
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { step, email, setEmail, pending, error, clearError, notice, cooldown, attempt, sendCode, verify, changeEmail };
}

export type EmailOtpFlow = ReturnType<typeof useEmailOtp>;
