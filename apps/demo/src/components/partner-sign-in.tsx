"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { Button, TextField } from "@juli/ui";

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

/**
 * "Tài khoản đối tác" (fast track P32-A, D42, AC-32.2): e-mail + password for
 * the trial accounts the Juli team creates for a partner platform's reviewer.
 * No sign-up and no "forgot password" here or anywhere. After GoTrue's
 * password grant the account is confirmed with `GET /v1/reviewer/me`: a
 * reviewer lands on Trang chủ with the reference shop selected; an expired or
 * revoked account, or a password user who is not a trial account, is signed
 * out again with the reason (dictionary.md `auth.password.*`).
 *
 * Lives only on `/auth/email` — never on the anonymous landing, whose module
 * graph must not reach a `/v1/*` route (`replay-module-graph.test.ts`); the
 * landing links here instead.
 */

export const PARTNER_SIGN_IN_TITLE = "Tài khoản đối tác (đăng nhập bằng mật khẩu)";

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
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const denial = denialFromLocation(window.location.search);
      if (denial) setError(PASSWORD_SIGN_IN_ERROR_COPY[denial]);
      if (denial || window.location.hash === "#doi-tac") setOpen(true);
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
      storeReviewerRecord({ platform: me.me.platform, expiresAt: me.me.expiresAt, sample: me.me.shop === null });
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

  return (
    <section aria-labelledby={`${baseId}-title`} className="partner-sign-in" id="doi-tac">
      <button
        aria-controls={`${baseId}-form`}
        aria-expanded={open}
        className="partner-sign-in__toggle"
        id={`${baseId}-title`}
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        {PARTNER_SIGN_IN_TITLE}
      </button>
      <div hidden={!open} id={`${baseId}-form`}>
        {open ? (
          <form aria-label={PASSWORD_SIGN_IN_LABEL} className="email-sign-in" noValidate onSubmit={onSubmit}>
            <p className="partner-sign-in__help">Chỉ dành cho tài khoản dùng thử Juli cấp cho đối tác.</p>
            <TextField
              autoComplete="username"
              id={`${baseId}-email`}
              inputMode="email"
              label="Email"
              name="email"
              onChange={(event) => setEmail(event.target.value)}
              type="email"
              value={email}
            />
            <TextField
              autoComplete="current-password"
              errorMessage={error ?? undefined}
              id={`${baseId}-password`}
              label="Mật khẩu"
              name="password"
              onChange={(event) => {
                setPassword(event.target.value);
                if (error) setError(null);
              }}
              type="password"
              value={password}
            />
            <div className="email-sign-in__actions">
              <Button disabled={pending} type="submit">
                {pending ? "Đang đăng nhập…" : "Đăng nhập"}
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </section>
  );
}
