import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ensureFreshSession,
  installAuthRefresh,
  setAuthRefreshRedirect,
  uninstallAuthRefreshForTests,
} from "../auth-refresh";
import { storeReviewerRecord, clearReviewerRecord } from "../reviewer/session";
import { AUTH_SESSION_STORAGE_KEY, readAuthSession, storeAuthSession } from "../supabase-auth";

function jwt(expSeconds: number): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
  return `${b64({ alg: "none" })}.${b64({ exp: expSeconds })}.sig`;
}
const nowS = () => Math.floor(Date.now() / 1000);
const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

let calls: { url: string; auth: string | null; body?: string }[];
let handler: (url: string, auth: string | null) => Response;
let redirect: ReturnType<typeof vi.fn<(href: string) => void>>;
const REFRESHED = jwt(nowS() + 3600);

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://proj.supabase.co");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon");
  window.localStorage.clear();
  window.sessionStorage.clear();
  calls = [];
  handler = (url, auth) => {
    if (url.includes("/auth/v1/token")) return json(200, { access_token: REFRESHED, refresh_token: "r2", expires_in: 3600 });
    return json(auth === `Bearer ${REFRESHED}` ? 200 : 401, {});
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init?: RequestInit) => {
      const headers = new Headers(init?.headers);
      const auth = headers.get("Authorization");
      calls.push({ url: String(input), auth, body: init?.body as string | undefined });
      return handler(String(input), auth);
    }),
  );
  window.fetch = globalThis.fetch;
  redirect = vi.fn<(href: string) => void>();
  setAuthRefreshRedirect(redirect);
});

afterEach(() => {
  uninstallAuthRefreshForTests();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  clearReviewerRecord();
});

const tokenCalls = () => calls.filter((c) => c.url.includes("/auth/v1/token"));
const store = (accessToken: string, refreshToken: string | null = "r1") =>
  storeAuthSession({ accessToken, refreshToken, expiresIn: 3600, tokenType: "bearer" });
const api = () => window.fetch("/v1/reviewer/me", { headers: { Authorization: `Bearer ${readAuthSession()?.accessToken}` } });

describe("auth refresh", () => {
  it("refreshes an expired token at load, stores the rotated session", async () => {
    store(jwt(nowS() - 10));
    const session = await ensureFreshSession();
    expect(tokenCalls()).toHaveLength(1);
    expect(tokenCalls()[0].url).toContain("grant_type=refresh_token");
    expect(JSON.parse(tokenCalls()[0].body ?? "{}")).toEqual({ refresh_token: "r1" });
    expect(session?.accessToken).toBe(REFRESHED);
    expect(readAuthSession()).toMatchObject({ accessToken: REFRESHED, refreshToken: "r2" });
  });

  it("does not refresh a token that is still valid", async () => {
    store(jwt(nowS() + 600));
    await ensureFreshSession();
    expect(tokenCalls()).toHaveLength(0);
  });

  it("legacy session (opaque token, no exp) is used as is", async () => {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "opaque", tokenType: "bearer" }));
    const session = await ensureFreshSession();
    expect(session?.accessToken).toBe("opaque");
    expect(tokenCalls()).toHaveLength(0);
  });

  it("on 401 refreshes once and retries once with the new token", async () => {
    store(jwt(nowS() + 600));
    installAuthRefresh();
    const res = await api();
    expect(res.status).toBe(200);
    expect(tokenCalls()).toHaveLength(1);
    const v1 = calls.filter((c) => c.url.startsWith("/v1/"));
    expect(v1).toHaveLength(2);
    expect(v1[1].auth).toBe(`Bearer ${REFRESHED}`);
  });

  it("a second 401 is returned without further retries", async () => {
    store(jwt(nowS() + 600));
    installAuthRefresh();
    handler = (url) =>
      url.includes("/auth/v1/token") ? json(200, { access_token: REFRESHED, refresh_token: "r2" }) : json(401, {});
    const res = await api();
    expect(res.status).toBe(401);
    expect(tokenCalls()).toHaveLength(1);
    expect(calls.filter((c) => c.url.startsWith("/v1/"))).toHaveLength(2);
  });

  it("concurrent 401s share a single refresh", async () => {
    store(jwt(nowS() + 600));
    installAuthRefresh();
    const results = await Promise.all([api(), api(), api()]);
    expect(results.map((r) => r.status)).toEqual([200, 200, 200]);
    expect(tokenCalls()).toHaveLength(1);
  });

  it("refresh rejected: seller session cleared, redirected to sign-in", async () => {
    store(jwt(nowS() + 600));
    installAuthRefresh();
    handler = (url) => (url.includes("/auth/v1/token") ? json(400, { error_code: "refresh_token_not_found" }) : json(401, {}));
    const res = await api();
    expect(res.status).toBe(401);
    expect(readAuthSession()).toBeNull();
    expect(redirect).toHaveBeenCalledWith("/auth/email");
    expect(tokenCalls()).toHaveLength(1);
  });

  it("refresh rejected: reviewer is sent to /auth/email#doi-tac", async () => {
    storeReviewerRecord({ platform: "shopee", expiresAt: "2099-01-01T00:00:00Z", sample: true });
    store(jwt(nowS() - 5), null);
    expect(await ensureFreshSession()).toBeNull();
    expect(tokenCalls()).toHaveLength(0);
    expect(readAuthSession()).toBeNull();
    expect(redirect).toHaveBeenCalledWith("/auth/email#doi-tac");
  });

  it("a transient refresh failure keeps the session", async () => {
    store(jwt(nowS() - 5));
    handler = () => json(503, {});
    await ensureFreshSession();
    expect(readAuthSession()).not.toBeNull();
    expect(redirect).not.toHaveBeenCalled();
  });
});
