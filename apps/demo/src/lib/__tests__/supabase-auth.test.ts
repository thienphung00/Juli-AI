import { afterEach, beforeEach, describe, expect, it } from "vitest";

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
  });

  it("round-trips a stored session under its own dedicated key", () => {
    storeAuthSession({
      accessToken: "abc.def.ghi",
      refreshToken: "r-1",
      expiresIn: 3600,
      tokenType: "bearer",
    });

    expect(
      window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY),
    ).not.toBeNull();
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
    window.sessionStorage.setItem(AUTH_SESSION_STORAGE_KEY, "{not json");

    expect(readAuthSession()).toBeNull();
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
