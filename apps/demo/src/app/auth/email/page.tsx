"use client";

import Link from "next/link";

import { EmailSignIn } from "../../../components/email-sign-in";
import { LegalConsentNote } from "../../../components/legal-consent-note";
import { EMAIL_SIGN_IN_LABEL } from "../../../lib/supabase-auth";

/**
 * "Đăng nhập bằng email" as a page (AC-9.1) — where the shop-avatar menu's
 * email item leads, beside its Google item. The landing door renders the same
 * `EmailSignIn` inline.
 */
export default function EmailSignInPage() {
  return (
    <section aria-labelledby="email-sign-in-title" className="demo-placeholder">
      <p className="demo-kicker">Tài khoản thật của bạn</p>
      <h1 id="email-sign-in-title">{EMAIL_SIGN_IN_LABEL}</h1>
      <p>
        Nhập email, Juli gửi mã 6 chữ số. Đăng nhập xong, bạn đến màn hình Kết
        nối TikTok Shop.
      </p>
      <EmailSignIn autoFocus />
      <LegalConsentNote />
      <Link className="demo-placeholder__recovery" href="/?entry=door">
        Đăng nhập với Google thay vì email
      </Link>
    </section>
  );
}
