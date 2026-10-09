import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_SESSION_STORAGE_KEY,
  buildGoogleAuthorizeUrl,
  clearAuthSession,
  decodeJwtPayload,
  parseAuthCallbackHash,
  readAuthSession,
  storeAuthSession,
} from "../supabase-auth";

const ORIGINAL_ENV = { ...process.env };

function setSupabaseEnv() {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://rmxzbvgiwrvjuzlzqdcz.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key-for-tests";
}

function clearSupabaseEnv() {
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
}

describe("buildGoogleAuthorizeUrl", () => {
  afterEach(() => {
    process.env = { ...ORIGINAL_ENV };
  });

  it("points at the configured Supabase project's Google authorize endpoint, carrying the redirect and anon key", () => {
    setSupabaseEnv();

    const url = buildGoogleAuthorizeUrl("https://demo.app-juli.com/auth/callback");

    expect(url).not.toBeNull();
    const parsed = new URL(url as string);
    expect(parsed.origin).toBe("https://rmxzbvgiwrvjuzlzqdcz.supabase.co");
    expect(parsed.pathname).toBe("/auth/v1/authorize");
    expect(parsed.searchParams.get("provider")).toBe("google");
    expect(parsed.searchParams.get("redirect_to")).toBe(
      "https://demo.app-juli.com/auth/callback",
    );
    expect(parsed.searchParams.get("apikey")).toBe("anon-key-for-tests");
  });

  it("returns null rather than a broken link when Supabase config is missing", () => {
    clearSupabaseEnv();

    expect(buildGoogleAuthorizeUrl("https://demo.app-juli.com/auth/callback")).toBeNull();
  });
});

describe("parseAuthCallbackHash", () => {
  it("extracts a session from a successful implicit-grant redirect", () => {
    const hash =
      "#access_token=abc.def.ghi&refresh_token=r-1&expires_in=3600&token_type=bearer";

    const result = parseAuthCallbackHash(hash);

    expect(result).toEqual({
      status: "success",
      session: {
        accessToken: "abc.def.ghi",
        refreshToken: "r-1",
        expiresIn: 3600,
        tokenType: "bearer",
      },
    });
  });

  it("surfaces a provider error honestly instead of silently falling through", () => {
    const hash =
      "#error=access_denied&error_code=user_cancelled&error_description=User%20cancelled%20login";

    const result = parseAuthCallbackHash(hash);

    expect(result).toEqual({
      status: "error",
      message: "User cancelled login",
      errorCode: "user_cancelled",
    });
  });

  it("reports an empty hash as empty, not as a fabricated success", () => {
    expect(parseAuthCallbackHash("")).toEqual({ status: "empty" });
    expect(parseAuthCallbackHash("#")).toEqual({ status: "empty" });
  });
});

describe("auth session storage", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    window.localStorage.clear();
  });

  it("round-trips a stored session under its own dedicated key", () => {
    storeAuthSession({
      accessToken: "abc.def.ghi",
      refreshToken: "r-1",
      expiresIn: 3600,
      tokenType: "bearer",
    });

    // P11: localStorage (Supabase's default) — survives new tabs and a restart.
    expect(
      window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY),
    ).not.toBeNull();
    expect(window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
    expect(readAuthSession()).toEqual({
      accessToken: "abc.def.ghi",
      refreshToken: "r-1",
      expiresIn: 3600,
      tokenType: "bearer",
    });
  });

  it("returns null when nothing is stored, and after clearing", () => {
    expect(readAuthSession()).toBeNull();

    storeAuthSession({
      accessToken: "abc.def.ghi",
      refreshToken: "r-1",
      expiresIn: 3600,
      tokenType: "bearer",
    });
    clearAuthSession();

    expect(readAuthSession()).toBeNull();
  });

  it("returns null for corrupted storage rather than throwing", () => {
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, "{not json");

    expect(readAuthSession()).toBeNull();
  });

  it("moves a session an older build left in sessionStorage over to localStorage, once", () => {
    const legacy = { accessToken: "old.tab.token", refreshToken: null, expiresIn: null, tokenType: "bearer" };
    window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(legacy));

    expect(readAuthSession()).toEqual(legacy);
    expect(JSON.parse(window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY) as string)).toEqual(legacy);
    expect(window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
  });

  it("sign-out clears the session from both stores", () => {
    window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "a" }));
    window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "b" }));

    clearAuthSession();

    expect(window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
    expect(window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY)).toBeNull();
    expect(readAuthSession()).toBeNull();
  });

  it("never throws when the browser blocks storage", () => {
    const blocked = vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    try {
      expect(() =>
        storeAuthSession({ accessToken: "x", refreshToken: null, expiresIn: null, tokenType: "bearer" }),
      ).not.toThrow();
      // Falls back to the tab's sessionStorage so this tab still signs in.
      expect(readAuthSession()?.accessToken).toBe("x");
      expect(() => clearAuthSession()).not.toThrow();
      expect(readAuthSession()).toBeNull();
    } finally {
      blocked.mockRestore();
    }
  });
});

describe("decodeJwtPayload", () => {
  it("decodes the payload for display only — no signature verification implied", () => {
    // header.payload.signature, payload = {"sub":"u1","email":"seller@example.com"}
    const token =
      "eyJhbGciOiJIUzI1NiJ9." +
      "eyJzdWIiOiJ1MSIsImVtYWlsIjoic2VsbGVyQGV4YW1wbGUuY29tIn0." +
      "signature-not-checked-client-side";

    expect(decodeJwtPayload(token)).toEqual({
      sub: "u1",
      email: "seller@example.com",
    });
  });

  it("returns null for a malformed token instead of throwing", () => {
    expect(decodeJwtPayload("not-a-jwt")).toBeNull();
  });
});
