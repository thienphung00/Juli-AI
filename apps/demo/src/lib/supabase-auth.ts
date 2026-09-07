/**
 * Supabase Auth (Google provider) for the "Đăng nhập với Google" door —
 * ADR-094 decision 3. Deliberately hand-rolled against the plain GoTrue REST
 * surface rather than the `@supabase/supabase-js` SDK: the only operation
 * this app needs is a browser redirect plus reading the implicit-grant hash
 * GoTrue appends on return, and `apps/demo`'s existing contract (#397,
 * `lib/analytics/api-client.ts`) is already "no client SDK, plain fetch".
 *
 * This is a real, distinct Supabase Auth identity (ADR-075 unweakened) — not
 * the withdrawn anonymous session from ADR-084 decision 1.
 */

export interface AuthSession {
  accessToken: string;
  refreshToken: string | null;
  expiresIn: number | null;
  tokenType: string;
}

export type AuthCallbackResult =
  | { status: "success"; session: AuthSession }
  | { status: "error"; message: string }
  | { status: "empty" };

export const AUTH_SESSION_STORAGE_KEY = "juli_demo_auth_session";

function readSupabaseConfig(): { url: string; anonKey: string } | null {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (!url || !anonKey) {
    return null;
  }

  return { url, anonKey };
}

/** Whether "Đăng nhập với Google" has anywhere to go — used to render an
 * honest disabled state instead of a link to nowhere when env is missing. */
export function isGoogleSignInConfigured(): boolean {
  return readSupabaseConfig() !== null;
}

/**
 * Builds the Supabase GoTrue authorize URL for a full-page browser redirect.
 * Returns null (never a broken link) when the project URL/anon key are not
 * configured in this environment.
 */
export function buildGoogleAuthorizeUrl(redirectTo: string): string | null {
  const config = readSupabaseConfig();

  if (!config) {
    return null;
  }

  const authorizeUrl = new URL("/auth/v1/authorize", config.url);
  authorizeUrl.searchParams.set("provider", "google");
  authorizeUrl.searchParams.set("redirect_to", redirectTo);
  authorizeUrl.searchParams.set("apikey", config.anonKey);

  return authorizeUrl.toString();
}

/**
 * Parses the `#access_token=...` (or `#error=...`) hash fragment GoTrue's
 * implicit grant appends to `redirect_to` on return from Google.
 */
export function parseAuthCallbackHash(hash: string): AuthCallbackResult {
  const trimmed = hash.startsWith("#") ? hash.slice(1) : hash;

  if (!trimmed) {
    return { status: "empty" };
  }

  const params = new URLSearchParams(trimmed);
  const error = params.get("error");

  if (error) {
    const description = params.get("error_description");
    return {
      status: "error",
      message: description ? decodeURIComponent(description.replace(/\+/g, " ")) : error,
    };
  }

  const accessToken = params.get("access_token");

  if (!accessToken) {
    return { status: "empty" };
  }

  const expiresInRaw = params.get("expires_in");

  return {
    status: "success",
    session: {
      accessToken,
      refreshToken: params.get("refresh_token"),
      expiresIn: expiresInRaw ? Number(expiresInRaw) : null,
      tokenType: params.get("token_type") ?? "bearer",
    },
  };
}

export function storeAuthSession(session: AuthSession): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(
    AUTH_SESSION_STORAGE_KEY,
    JSON.stringify(session),
  );
}

export function readAuthSession(): AuthSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  const raw = window.sessionStorage.getItem(AUTH_SESSION_STORAGE_KEY);

  if (!raw) {
    return null;
  }

  try {
    const parsed = JSON.parse(raw) as Partial<AuthSession>;

    if (typeof parsed.accessToken !== "string") {
      return null;
    }

    return {
      accessToken: parsed.accessToken,
      refreshToken: parsed.refreshToken ?? null,
      expiresIn: parsed.expiresIn ?? null,
      tokenType: parsed.tokenType ?? "bearer",
    };
  } catch {
    return null;
  }
}

export function clearAuthSession(): void {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}

/**
 * Decodes a JWT payload for **display only** (e.g. an email to greet the
 * seller with). This performs no signature verification and must never be
 * treated as proof of identity — that check happens server-side
 * (`verify_supabase_jwt`, ADR-075).
 */
export function decodeJwtPayload(token: string): Record<string, unknown> | null {
  const parts = token.split(".");

  if (parts.length !== 3) {
    return null;
  }

  try {
    const base64 = parts[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), "=");
    const json =
      typeof atob === "function"
        ? atob(padded)
        : Buffer.from(padded, "base64").toString("utf8");

    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}
