/**
 * Keeps the signed-in session alive (P64): Supabase access tokens last ~1 h.
 *
 *  - `ensureFreshSession()` refreshes first when the token expires within 60 s;
 *  - `installAuthRefresh()` wraps `window.fetch` so any `/v1/*` call carrying
 *    the stored Bearer token that comes back 401 is refreshed once and retried
 *    once (covers every API client and the SSE client without touching them),
 *    and schedules a refresh ~60 s before expiry while the tab is open;
 *  - refresh calls are single-flight; a refresh GoTrue rejects ends the
 *    sign-in (session cleared, redirect to the right sign-in).
 *
 * Tokens are never logged. Sessions without a decodable `exp` (legacy) are
 * left to the reactive 401 path.
 */

import { clearReviewerSignIn } from "./reviewer/mode";
import { readReviewerRecord } from "./reviewer/session";
import {
  clearAuthSession,
  decodeJwtPayload,
  readAuthSession,
  refreshSessionRequest,
  storeAuthSession,
  type AuthSession,
} from "./supabase-auth";

export const REFRESH_LEAD_SECONDS = 60;
const SELLER_SIGN_IN_PATH = "/auth/email";
const REVIEWER_SIGN_IN_PATH = "/auth/email#doi-tac";

/** Absolute expiry (ms epoch) from the JWT `exp` claim, or null when unknown. */
export function sessionExpiryMs(session: AuthSession): number | null {
  const exp = decodeJwtPayload(session.accessToken)?.exp;
  return typeof exp === "number" ? exp * 1000 : null;
}

function expiresWithin(session: AuthSession, seconds: number, now = Date.now()): boolean {
  const expiry = sessionExpiryMs(session);
  return expiry !== null && expiry - now <= seconds * 1000;
}

let inFlight: Promise<AuthSession | null> | null = null;
let redirectImpl: (href: string) => void = (href) => window.location.assign(href);

/** Test seam. */
export function setAuthRefreshRedirect(fn: (href: string) => void): void {
  redirectImpl = fn;
}

function endSignIn(): void {
  const reviewer = readReviewerRecord() !== null;
  if (reviewer) clearReviewerSignIn();
  else clearAuthSession();
  if (typeof window === "undefined") return;
  if (window.location.pathname.startsWith("/auth/") && !reviewer) return;
  redirectImpl(reviewer ? REVIEWER_SIGN_IN_PATH : SELLER_SIGN_IN_PATH);
}

/**
 * Refreshes the stored session (single-flight). Resolves the new session, or
 * null when the sign-in ended (cleared + redirected) or the refresh was
 * transient (stored session kept).
 */
export function refreshAuthSession(): Promise<AuthSession | null> {
  if (inFlight) return inFlight;
  const current = readAuthSession();
  if (!current) return Promise.resolve(null);
  inFlight = (async () => {
    const result = await refreshSessionRequest(current.refreshToken, (input, init) => rawFetch(input, init));
    if (result.ok) {
      storeAuthSession(result.session);
      scheduleRefresh();
      return result.session;
    }
    if (result.reason !== "transient") endSignIn();
    return null;
  })().finally(() => {
    inFlight = null;
  });
  return inFlight;
}

/** The session to use now: refreshed first when it expires within 60 s. */
export async function ensureFreshSession(): Promise<AuthSession | null> {
  const session = readAuthSession();
  if (!session) return null;
  if (!expiresWithin(session, REFRESH_LEAD_SECONDS)) return session;
  return (await refreshAuthSession()) ?? readAuthSession();
}

let timer: number | undefined;

function scheduleRefresh(): void {
  if (typeof window === "undefined") return;
  window.clearTimeout(timer);
  const session = readAuthSession();
  const expiry = session ? sessionExpiryMs(session) : null;
  if (expiry === null) return;
  const delay = Math.max(1000, expiry - Date.now() - REFRESH_LEAD_SECONDS * 1000);
  // setTimeout caps at 2^31-1 ms; a longer wait just re-schedules.
  timer = window.setTimeout(() => {
    void ensureFreshSession().then(scheduleRefresh);
  }, Math.min(delay, 2_000_000_000));
}

let originalFetch: typeof fetch | null = null;
function rawFetch(input: string, init?: RequestInit): Promise<Response> {
  return (originalFetch ?? fetch)(input, init);
}

function bearerOf(headers: Headers): string | null {
  const value = headers.get("Authorization");
  return value && /^Bearer /i.test(value) ? value.slice(7) : null;
}

function isApiUrl(url: string): boolean {
  try {
    const parsed = new URL(url, window.location.origin);
    return parsed.pathname.startsWith("/v1/") || parsed.pathname.includes("/v1/");
  } catch {
    return false;
  }
}

/** Idempotent. Wraps `window.fetch` and starts the proactive timer. */
export function installAuthRefresh(): void {
  if (typeof window === "undefined" || originalFetch) return;
  originalFetch = window.fetch.bind(window);
  const base = originalFetch;

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : null;
    const headers = new Headers(init?.headers);
    const sent = bearerOf(headers);
    if (url === null || sent === null || !isApiUrl(url)) return base(input, init);

    const response = await base(input, init);
    if (response.status !== 401) return response;

    // Another caller may already have rotated the token; only refresh when the
    // rejected token is still the stored one.
    const stored = readAuthSession();
    if (!stored) return response;
    const next = stored.accessToken !== sent ? stored : await refreshAuthSession();
    if (!next || next.accessToken === sent) return response;

    headers.set("Authorization", `Bearer ${next.accessToken}`);
    return base(input, { ...init, headers });
  };

  scheduleRefresh();
}

/** Test seam: undo `installAuthRefresh`. */
export function uninstallAuthRefreshForTests(): void {
  if (typeof window !== "undefined") {
    window.clearTimeout(timer);
    if (originalFetch) window.fetch = originalFetch;
  }
  originalFetch = null;
  inFlight = null;
}
