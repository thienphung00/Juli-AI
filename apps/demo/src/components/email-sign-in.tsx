"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { Button, TextField } from "@juli/ui";

import {
  EMAIL_OTP_ERROR_COPY,
  EMAIL_OTP_RESEND_COOLDOWN_SECONDS,
  isValidEmail,
  normaliseOtpCode,
  requestEmailOtp,
  storeAuthSession,
  verifyEmailOtp,
  type AuthSession,
  type EmailOtpFailure,
} from "../lib/supabase-auth";
import { reportTikTokRegistration } from "../lib/tiktok-registration";

/**
 * "Đăng nhập bằng email" (AC-9.1): email → "Gửi mã" → the 6-digit code →
 * signed in. The same email also carries a magic link to `/auth/callback`,
 * handled there. On success the session is stored exactly as the Google
 * callback stores it, then a FULL load to `/auth/connect-shop` — so the
 * shell's providers (which resolve the session once, on mount) see it.
 *
 * Nothing here echoes the code: errors are fixed Vietnamese sentences
 * (`EMAIL_OTP_ERROR_COPY`), never GoTrue's text.
 */

export interface EmailSignInProps {
  /** After the session is stored. Default: report the sign-up, full load to connect-shop. */
  readonly onSignedIn?: (session: AuthSession) => void;
  readonly autoFocus?: boolean;
}

function defaultOnSignedIn(session: AuthSession) {
  // Same order as the Google callback: session first, the conversion report
  // fire-and-forget, so it can never cost the seller their sign-in.
  void reportTikTokRegistration(session.accessToken);
  window.location.assign("/auth/connect-shop");
}

type Step = "email" | "code";

export function EmailSignIn({ onSignedIn = defaultOnSignedIn, autoFocus = false }: EmailSignInProps) {
  const baseId = useId();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = window.setTimeout(() => setCooldown((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearTimeout(timer);
  }, [cooldown]);

  const showFailure = (failure: EmailOtpFailure) => {
    setError(EMAIL_OTP_ERROR_COPY[failure.error]);
    if (failure.error === "rate_limited") {
      setCooldown(failure.retryAfterSeconds ?? EMAIL_OTP_RESEND_COOLDOWN_SECONDS);
    }
  };

  const sendCode = async () => {
    const trimmed = email.trim();
    if (!isValidEmail(trimmed)) {
      setError(EMAIL_OTP_ERROR_COPY.invalid_email);
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
    setEmail(trimmed);
    setCode("");
    setStep("code");
    setCooldown(EMAIL_OTP_RESEND_COOLDOWN_SECONDS);
    setNotice(
      `Đã gửi mã 6 chữ số tới ${trimmed}. Nhập mã bên dưới, hoặc bấm nút đăng nhập trong email.`,
    );
  };

  const verify = async () => {
    const digits = normaliseOtpCode(code);
    if (digits.length < 6) {
      setError("Nhập đủ 6 chữ số trong email.");
      return;
    }
    setPending(true);
    setError(null);
    const result = await verifyEmailOtp(email, digits);
    if (!result.ok) {
      setPending(false);
      setCode("");
      showFailure(result);
      return;
    }
    storeAuthSession(result.session);
    setNotice("Đăng nhập thành công. Đang chuyển tới Kết nối TikTok Shop…");
    onSignedIn(result.session);
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending) return;
    void (step === "email" ? sendCode() : verify());
  };

  const changeEmail = () => {
    setStep("email");
    setCode("");
    setError(null);
    setNotice(null);
  };

  const resendLabel = cooldown > 0 ? `Gửi lại mã sau ${cooldown} giây` : "Gửi lại mã";

  return (
    <form
      aria-label="Đăng nhập bằng email"
      className="email-sign-in"
      noValidate
      onSubmit={onSubmit}
    >
      {step === "email" ? (
        <>
          <TextField
            autoComplete="email"
            autoFocus={autoFocus}
            errorMessage={error ?? undefined}
            helperText="Juli gửi mã đăng nhập 6 chữ số tới email này. Chưa có tài khoản? Juli tạo cho bạn."
            id={`${baseId}-email`}
            inputMode="email"
            label="Email"
            name="email"
            onChange={(event) => {
              setEmail(event.target.value);
              if (error) setError(null);
            }}
            placeholder="ten@shopcuaban.vn"
            type="email"
            value={email}
          />
          <div className="email-sign-in__actions">
            <Button disabled={pending || cooldown > 0} type="submit">
              {pending ? "Đang gửi mã…" : cooldown > 0 ? `Gửi mã sau ${cooldown} giây` : "Gửi mã"}
            </Button>
          </div>
        </>
      ) : (
        <>
          {notice ? (
            <p className="email-sign-in__notice" role="status">
              {notice}
            </p>
          ) : null}
          <TextField
            autoComplete="one-time-code"
            autoFocus
            errorMessage={error ?? undefined}
            id={`${baseId}-code`}
            inputMode="numeric"
            label="Mã đăng nhập (6 chữ số)"
            maxLength={12}
            name="code"
            onChange={(event) => {
              setCode(event.target.value);
              if (error) setError(null);
            }}
            pattern="[0-9 ]*"
            value={code}
          />
          <div className="email-sign-in__actions">
            <Button disabled={pending} type="submit">
              {pending ? "Đang xác nhận…" : "Xác nhận"}
            </Button>
            <Button
              disabled={pending || cooldown > 0}
              onClick={() => void sendCode()}
              type="button"
              variant="secondary"
            >
              {resendLabel}
            </Button>
            <Button disabled={pending} onClick={changeEmail} type="button" variant="ghost">
              Dùng email khác
            </Button>
          </div>
        </>
      )}
    </form>
  );
}
