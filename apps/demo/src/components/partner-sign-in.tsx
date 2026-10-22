"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { fetchReviewerMe, type ReviewerMeResult } from "../lib/reviewer/api-client";
import { storeReviewerRecord } from "../lib/reviewer/session";
import { clearReviewerSignIn } from "../lib/reviewer/mode";
import { clearActiveShop, storeActiveShop } from "../lib/shop-session";
import {
  PASSWORD_SIGN_IN_ERROR_COPY,
  PASSWORD_SIGN_IN_LABEL,
  signInWithPassword,
  storeAuthSession,
  type PasswordSignInErrorKind,
  type PasswordSignInResult,
} from "../lib/supabase-auth";
import { AuthAlert, AuthSpinner } from "./auth/auth-alert";

/**
 * "Tài khoản đối tác" (fast track P32-A, D42, AC-32.2): e-mail + password for
 * the trial accounts the Juli team creates for a partner platform's reviewer.
 * No sign-up and no "forgot password" here or anywhere. After GoTrue's
 * password grant the account is confirmed with `GET /v1/reviewer/me`: a
 * reviewer lands on Trang chủ (with the reference shop selected when one is
 * pinned); an expired or revoked account, or a password user who is not a
 * trial account, is signed out again with the reason (dictionary.md
 * `auth.password.*`).
 *
 * Since P34-F (D44.5) this is only the form; the auth screen's partner view
 * (`auth/auth-screen.tsx`) wraps it with its heading and "← Quay lại". It is
 * handed to that screen only on `/auth/email` — never on the anonymous
 * landing, whose module graph must not reach a `/v1/*` route
 * (`replay-module-graph.test.ts`); the landing's footer links to
 * `/auth/email#doi-tac` instead.
 */

export interface PartnerSignInProps {
  readonly signIn?: (email: string, password: string) => Promise<PasswordSignInResult>;
  readonly fetchMe?: (token: string) => Promise<ReviewerMeResult>;
  readonly onSignedIn?: () => void;
}

const DENIAL_ERRORS: Readonly<Record<string, PasswordSignInErrorKind>> = {
  expired: "expired",
  revoked: "revoked",
  unknown: "not_trial",
};

/** `/auth/email?doi-tac=<denial>` — where the shell sends a denied reviewer. */
export function denialFromLocation(search: string): PasswordSignInErrorKind | null {
  const value = new URLSearchParams(search).get("doi-tac");
  return value ? (DENIAL_ERRORS[value] ?? null) : null;
}

export function PartnerSignIn({
  signIn = (email, password) => signInWithPassword(email, password),
  fetchMe = (token) => fetchReviewerMe(token),
  onSignedIn = () => window.location.assign("/"),
}: PartnerSignInProps) {
  const baseId = useId();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const denial = denialFromLocation(window.location.search);
      if (denial) setError(PASSWORD_SIGN_IN_ERROR_COPY[denial]);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const fail = (kind: PasswordSignInErrorKind) => {
    setPending(false);
    setPassword("");
    setError(PASSWORD_SIGN_IN_ERROR_COPY[kind]);
  };

  const submit = async () => {
    setPending(true);
    setError(null);
    const result = await signIn(email, password);
    if (!result.ok) {
      fail(result.error);
      return;
    }
    storeAuthSession(result.session);
    const me = await fetchMe(result.session.accessToken);
    if (me.status === "reviewer") {
      // P32-D (D42 amendment): no pinned shop → no active shop, so every page
      // shows the bundled sample shop (P13's no-shop door) and calls no shop API.
      if (me.me.shop) storeActiveShop({ id: me.me.shop.id, name: me.me.shop.name });
      else clearActiveShop();
      storeReviewerRecord({
        platform: me.me.platform,
        expiresAt: me.me.expiresAt,
        sample: me.me.shop === null,
        ...(me.me.mode ? { mode: me.me.mode } : {}),
        ...(me.me.writesEnabled ? { writesEnabled: true } : {}),
      });
      onSignedIn();
      return;
    }
    clearReviewerSignIn();
    if (me.status === "not_reviewer") fail("not_trial");
    else if (me.status === "denied") fail(DENIAL_ERRORS[me.denial] ?? "unknown");
    else fail("network");
  };

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!pending) void submit();
  };

  const errorId = `${baseId}-error`;

  return (
    <form aria-label={PASSWORD_SIGN_IN_LABEL} className="auth-form" noValidate onSubmit={onSubmit}>
      <label className="auth-label" htmlFor={`${baseId}-email`}>
        Email
      </label>
      <input
        autoComplete="username"
        className="auth-input"
        id={`${baseId}-email`}
        inputMode="email"
        name="email"
        onChange={(event) => setEmail(event.target.value)}
        type="email"
        value={email}
      />
      <label className="auth-label auth-label--spaced" htmlFor={`${baseId}-password`}>
        Mật khẩu
      </label>
      <input
        aria-describedby={error ? errorId : undefined}
        aria-invalid={error ? true : undefined}
        autoComplete="current-password"
        className="auth-input"
        id={`${baseId}-password`}
        name="password"
        onChange={(event) => {
          setPassword(event.target.value);
          if (error) setError(null);
        }}
        type="password"
        value={password}
      />
      {error ? <AuthAlert id={errorId}>{error}</AuthAlert> : null}
      <button
        aria-busy={pending || undefined}
        className="auth-btn auth-btn--ink auth-form__submit"
        disabled={pending}
        type="submit"
      >
        {pending ? <AuthSpinner /> : null}
        {pending ? "Đang đăng nhập…" : "Đăng nhập"}
      </button>
    </form>
  );
}
