import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  EMAIL_OTP_ERROR_COPY,
  describeAuthCallbackError,
  isValidEmail,
  normaliseOtpCode,
  requestEmailOtp,
  verifyEmailOtp,
} from "../supabase-auth";

/**
 * AC-9.1 — the email OTP client against GoTrue's REST surface, with fetch
 * stubbed. The shapes asserted here are GoTrue's: POST /auth/v1/otp with
 * `redirect_to` as a query parameter (what supabase-js's `emailRedirectTo`
 * becomes), POST /auth/v1/verify with `type: "email"`, and the
 * `{ error_code, msg }` error body.
 */

const ORIGINAL_ENV = { ...process.env };
const PROJECT = "https://rmxzbvgiwrvjuzlzqdcz.supabase.co";
const REDIRECT = "https://demo.app-juli.com/auth/callback";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = PROJECT;
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key-for-tests";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("isValidEmail / normaliseOtpCode", () => {
  it("accepts ordinary addresses and rejects malformed ones", () => {
    expect(isValidEmail("chu.shop@gmail.com")).toBe(true);
    expect(isValidEmail("  ban@shopcuaban.vn  ")).toBe(true);
    expect(isValidEmail("chushop")).toBe(false);
    expect(isValidEmail("chu shop@gmail.com")).toBe(false);
    expect(isValidEmail("a@b")).toBe(false);
  });

  it("keeps digits only, so a pasted '123 456' or '123-456' works", () => {
    expect(normaliseOtpCode("123 456")).toBe("123456");
    expect(normaliseOtpCode("123-456\n")).toBe("123456");
  });
});

describe("requestEmailOtp", () => {
  it("POSTs to the project's /auth/v1/otp with the anon key, create_user and the magic-link redirect", async () => {
    const fetchImpl = vi.fn(async () => json(200, {}));

    const result = await requestEmailOtp(" ban@shopcuaban.vn ", REDIRECT, fetchImpl);

    expect(result).toEqual({ ok: true });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    const parsed = new URL(url);
    expect(parsed.origin).toBe(PROJECT);
    expect(parsed.pathname).toBe("/auth/v1/otp");
    expect(parsed.searchParams.get("redirect_to")).toBe(REDIRECT);
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>).apikey).toBe("anon-key-for-tests");
    expect(JSON.parse(init.body as string)).toEqual({ email: "ban@shopcuaban.vn", create_user: true });
  });

  it("rejects a malformed email without calling GoTrue", async () => {
    const fetchImpl = vi.fn();
    expect(await requestEmailOtp("chushop", REDIRECT, fetchImpl)).toEqual({ ok: false, error: "invalid_email" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("is honestly unavailable, with no request, when Supabase is not configured", async () => {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    const fetchImpl = vi.fn();
    expect(await requestEmailOtp("ban@shopcuaban.vn", REDIRECT, fetchImpl)).toEqual({
      ok: false,
      error: "unavailable",
    });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("maps GoTrue's email-send rate limit to rate_limited, carrying the wait it names", async () => {
    const fetchImpl = vi.fn(async () =>
      json(429, {
        code: 429,
        error_code: "over_email_send_rate_limit",
        msg: "For security purposes, you can only request this after 42 seconds.",
      }),
    );
    expect(await requestEmailOtp("ban@shopcuaban.vn", REDIRECT, fetchImpl)).toEqual({
      ok: false,
      error: "rate_limited",
      retryAfterSeconds: 42,
    });
  });

  it("maps a bare 429 (project-wide email cap) to rate_limited", async () => {
    const fetchImpl = vi.fn(async () => json(429, { msg: "Email rate limit exceeded" }));
    expect(await requestEmailOtp("ban@shopcuaban.vn", REDIRECT, fetchImpl)).toEqual({
      ok: false,
      error: "rate_limited",
    });
  });

  it("maps GoTrue's invalid-address errors to invalid_email", async () => {
    const fetchImpl = vi.fn(async () =>
      json(400, { error_code: "email_address_invalid", msg: 'Email address "x@y.zz" is invalid' }),
    );
    expect(await requestEmailOtp("x@y.zz", REDIRECT, fetchImpl)).toEqual({ ok: false, error: "invalid_email" });
  });

  it("maps a disabled email provider / signups to unavailable", async () => {
    for (const code of ["otp_disabled", "email_provider_disabled", "signup_disabled"]) {
      const fetchImpl = vi.fn(async () => json(422, { error_code: code, msg: "disabled" }));
      expect(await requestEmailOtp("ban@shopcuaban.vn", REDIRECT, fetchImpl)).toEqual({
        ok: false,
        error: "unavailable",
      });
    }
  });

  it("maps a thrown fetch to network", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    expect(await requestEmailOtp("ban@shopcuaban.vn", REDIRECT, fetchImpl)).toEqual({ ok: false, error: "network" });
  });
});

describe("verifyEmailOtp", () => {
  const SESSION_BODY = {
    access_token: "eyJ.header.sig",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: 1_791_600_000,
    refresh_token: "r-email-1",
    user: { id: "11111111-1111-4111-8111-111111111111", email: "ban@shopcuaban.vn" },
  };

  it("POSTs type=email, the email and the digits-only code; returns the Google-shaped session", async () => {
    const fetchImpl = vi.fn(async () => json(200, SESSION_BODY));

    const result = await verifyEmailOtp("ban@shopcuaban.vn", "123 456", fetchImpl);

    expect(result).toEqual({
      ok: true,
      session: { accessToken: "eyJ.header.sig", refreshToken: "r-email-1", expiresIn: 3600, tokenType: "bearer" },
    });
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(new URL(url).pathname).toBe("/auth/v1/verify");
    expect((init.headers as Record<string, string>).apikey).toBe("anon-key-for-tests");
    expect(JSON.parse(init.body as string)).toEqual({ type: "email", email: "ban@shopcuaban.vn", token: "123456" });
  });

  it("maps GoTrue's expired/invalid token to invalid_code", async () => {
    const fetchImpl = vi.fn(async () =>
      json(403, { code: 403, error_code: "otp_expired", msg: "Token has expired or is invalid" }),
    );
    expect(await verifyEmailOtp("ban@shopcuaban.vn", "000000", fetchImpl)).toEqual({ ok: false, error: "invalid_code" });
  });

  it("maps a verify rate limit to rate_limited", async () => {
    const fetchImpl = vi.fn(async () => json(429, { error_code: "over_request_rate_limit", msg: "Request rate limit reached" }));
    expect(await verifyEmailOtp("ban@shopcuaban.vn", "123456", fetchImpl)).toEqual({ ok: false, error: "rate_limited" });
  });

  it("rejects a short code without calling GoTrue", async () => {
    const fetchImpl = vi.fn();
    expect(await verifyEmailOtp("ban@shopcuaban.vn", "12 34", fetchImpl)).toEqual({ ok: false, error: "invalid_code" });
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("never fabricates a session from a 200 without an access token", async () => {
    const fetchImpl = vi.fn(async () => json(200, { user: {} }));
    expect(await verifyEmailOtp("ban@shopcuaban.vn", "123456", fetchImpl)).toEqual({ ok: false, error: "unknown" });
  });
});

describe("copy", () => {
  it("every error sentence is Vietnamese, fixed, and carries no code or token", () => {
    for (const sentence of Object.values(EMAIL_OTP_ERROR_COPY)) {
      expect(sentence).not.toMatch(/\d{6}/);
      expect(sentence).not.toMatch(/token|otp_expired|rate limit/i);
    }
  });

  it("an expired magic link gets its own Vietnamese sentence; other failures keep the description", () => {
    expect(describeAuthCallbackError("Email link is invalid or has expired", "otp_expired")).toBe(
      "Liên kết đăng nhập đã hết hạn hoặc đã được dùng. Vui lòng gửi lại mã đăng nhập bằng email.",
    );
    expect(describeAuthCallbackError("User cancelled login", null)).toBe(
      "Đăng nhập không thành công: User cancelled login",
    );
  });
});
