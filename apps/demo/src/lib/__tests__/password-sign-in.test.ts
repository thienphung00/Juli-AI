import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PASSWORD_SIGN_IN_ERROR_COPY, signInWithPassword } from "../supabase-auth";
import { fetchReviewerMe, simulateDecision } from "../reviewer/api-client";

/**
 * P32-A (AC-32.2) — the partner trial account's password grant against
 * GoTrue's REST surface (fetch stubbed), and the two reviewer API calls.
 */

const ORIGINAL_ENV = { ...process.env };
const PROJECT = "https://rmxzbvgiwrvjuzlzqdcz.supabase.co";

function json(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = PROJECT;
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key-for-tests";
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

describe("signInWithPassword", () => {
  it("posts the password grant with the anon key and returns the session", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      json(200, { access_token: "at", refresh_token: "rt", expires_in: 3600, token_type: "bearer" }),
    );
    const result = await signInWithPassword(" shopee-review@app-juli.com ", "s3cret", fetchImpl);
    expect(result).toEqual({
      ok: true,
      session: { accessToken: "at", refreshToken: "rt", expiresIn: 3600, tokenType: "bearer" },
    });
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${PROJECT}/auth/v1/token?grant_type=password`);
    expect(init.method).toBe("POST");
    expect(init.headers.apikey).toBe("anon-key-for-tests");
    expect(JSON.parse(init.body)).toEqual({ email: "shopee-review@app-juli.com", password: "s3cret" });
  });

  it.each([
    [400, { error_code: "invalid_credentials", msg: "Invalid login credentials" }, "wrong"],
    [400, { error: "invalid_grant", error_description: "Invalid login credentials" }, "wrong"],
    [400, { error_code: "user_banned", msg: "User is banned" }, "revoked"],
    [400, { error_code: "email_not_confirmed" }, "unknown"],
    [429, { error_code: "over_request_rate_limit" }, "rate_limited"],
    [400, { error_code: "email_provider_disabled" }, "unavailable"],
    [500, {}, "unknown"],
  ])("maps GoTrue %s %j to %s", async (status, body, kind) => {
    const fetchImpl = vi.fn().mockResolvedValue(json(status, body));
    expect(await signInWithPassword("a@b.vn", "x", fetchImpl)).toEqual({ ok: false, error: kind });
  });

  it("network failure, missing config and empty input never reach GoTrue wrongly", async () => {
    expect(await signInWithPassword("a@b.vn", "x", vi.fn().mockRejectedValue(new TypeError("offline")))).toEqual({
      ok: false,
      error: "network",
    });
    const unused = vi.fn();
    expect(await signInWithPassword("not-an-email", "x", unused)).toEqual({ ok: false, error: "wrong" });
    expect(await signInWithPassword("a@b.vn", "", unused)).toEqual({ ok: false, error: "wrong" });
    expect(unused).not.toHaveBeenCalled();
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    expect(await signInWithPassword("a@b.vn", "x", unused)).toEqual({ ok: false, error: "unavailable" });
  });

  it("has Vietnamese copy for every error", () => {
    expect(PASSWORD_SIGN_IN_ERROR_COPY.wrong).toBe("Sai email hoặc mật khẩu.");
    expect(PASSWORD_SIGN_IN_ERROR_COPY.revoked).toBe("Tài khoản dùng thử này đã bị thu hồi. Vui lòng liên hệ Juli.");
    expect(PASSWORD_SIGN_IN_ERROR_COPY.expired).toBe("Tài khoản dùng thử này đã hết hạn. Vui lòng liên hệ Juli để gia hạn.");
  });
});

describe("reviewer API client", () => {
  it("GET /v1/reviewer/me: reviewer, not a reviewer, denied, error", async () => {
    const me = vi.fn().mockResolvedValue(
      json(200, {
        reviewer: true,
        platform: "shopee",
        expires_at: "2026-11-13T00:00:00Z",
        shop: { id: "alias-1", name: "Shop TikTok (ẩn danh)" },
      }),
    );
    expect(await fetchReviewerMe("tok", me)).toEqual({
      status: "reviewer",
      me: { reviewer: true, platform: "shopee", expiresAt: "2026-11-13T00:00:00Z", shop: { id: "alias-1", name: "Shop TikTok (ẩn danh)" } },
    });
    expect(me.mock.calls[0][0]).toBe("/v1/reviewer/me");
    expect(me.mock.calls[0][1].headers.Authorization).toBe("Bearer tok");
    expect(await fetchReviewerMe("tok", vi.fn().mockResolvedValue(json(200, { reviewer: false })))).toEqual({
      status: "not_reviewer",
    });
    for (const denial of ["expired", "revoked", "unknown"]) {
      const denied = vi.fn().mockResolvedValue(json(403, { detail: "x" }, { "X-Juli-Reviewer-Denied": denial }));
      expect(await fetchReviewerMe("tok", denied)).toEqual({ status: "denied", denial });
    }
    expect(await fetchReviewerMe("tok", vi.fn().mockResolvedValue(json(503, {})))).toEqual({
      status: "denied",
      denial: "unconfigured",
    });
    expect(await fetchReviewerMe("tok", vi.fn().mockResolvedValue(json(500, {})))).toEqual({ status: "error" });
  });

  it("POST simulate sends the step with the alias shop id and refuses a non-simulated body", async () => {
    const body = { simulated: true, step: "approve", action_card_id: "c1", label: "x", steps: [], change: {} };
    const ok = vi.fn().mockResolvedValue(json(200, body));
    expect(await simulateDecision("c1", "approve", { token: "tok", shopId: "alias-1", fetchImpl: ok })).toEqual(body);
    const [url, init] = ok.mock.calls[0];
    expect(url).toBe("/v1/reviewer/decisions/c1/simulate");
    expect(init.method).toBe("POST");
    expect(init.headers["X-Shop-Id"]).toBe("alias-1");
    expect(JSON.parse(init.body)).toEqual({ step: "approve" });
    await expect(
      simulateDecision("c1", "execute", { token: "t", shopId: "s", fetchImpl: vi.fn().mockResolvedValue(json(200, { simulated: false })) }),
    ).rejects.toThrow();
    await expect(
      simulateDecision("c1", "execute", { token: "t", shopId: "s", fetchImpl: vi.fn().mockResolvedValue(json(404, {})) }),
    ).rejects.toMatchObject({ status: 404 });
  });
});
