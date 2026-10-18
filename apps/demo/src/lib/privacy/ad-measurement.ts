/**
 * P50 (D60.6): whether this browser may send TikTok ad-measurement events.
 *
 * A signed-in seller who turned on "Không đo lường quảng cáo"
 * (`ad_measurement_opt_out`) gets no pixel and no event, from the pixel or
 * from the server relay. Until the preference of the signed-in seller is
 * known nothing is sent; a signed-out visitor is decided at once and without
 * a request (the replay's "nothing leaves the origin" promise,
 * `replay-module-graph.test.ts`, is about signed-out visitors).
 *
 * The ad-click-id gate (`hasTikTokAdReferral`) stays where it was, in front of
 * this one: this module is only consulted for a visitor an ad sent.
 */

import { readAuthSession } from "../supabase-auth";

/**
 * The privacy client is loaded by dynamic `import()`, only once a session
 * exists, the pattern of `components/impact-block.tsx`: this module is reached
 * from the sign-in door (`tiktok-registration.ts`), and the replay's
 * module-graph guard (`replay-module-graph.test.ts`) keeps every API
 * client out of the static graph a signed-out visitor loads.
 */
async function readOptOut(accessToken: string, fetchImpl: typeof fetch): Promise<boolean> {
  const { fetchPrivacy } = await import("./legal");
  return (await fetchPrivacy(accessToken, fetchImpl)).ad_measurement_opt_out;
}

export type AdMeasurement = "unknown" | "allowed" | "blocked";

/** The key the current decision was made for: an access token, or "" for signed out. */
let decidedFor: string | null = null;
let decision: AdMeasurement = "unknown";
let pending: Promise<AdMeasurement> | null = null;
let pendingFor: string | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function adMeasurement(): AdMeasurement {
  return decision;
}

export function subscribeAdMeasurement(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Removes TikTok's first-party cookies (`_ttp`, `_tt_*`, `ttcsid*`) on this
 * host and its parent domain. Copied from `apps/landing/src/lib/consent.ts`.
 */
export function clearTikTokCookies(): void {
  const host = window.location.hostname;
  for (const entry of document.cookie.split(";")) {
    const name = entry.split("=")[0]?.trim();
    if (!name || !/^(_ttp|_tt_|ttcsid)/.test(name)) continue;
    for (const domain of ["", `; domain=${host}`, `; domain=.${host}`]) {
      document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/${domain}`;
    }
  }
}

/** Tells an already loaded pixel to stop (its consent API, where present) and drops its cookies. */
function stopLoadedPixel(): void {
  const ttq = (window as unknown as { ttq?: { revokeConsent?: () => void; disableCookie?: () => void } }).ttq;
  try {
    ttq?.revokeConsent?.();
    ttq?.disableCookie?.();
  } catch {
    // A half-initialised pixel must not take the page down.
  }
  clearTikTokCookies();
}

/** Records a decision for `key`; blocking also stops a pixel that is already running. */
function decide(key: string, next: AdMeasurement): AdMeasurement {
  decidedFor = key;
  if (decision !== next) {
    decision = next;
    if (next === "blocked") stopLoadedPixel();
    notify();
  }
  return next;
}

/**
 * The seller just saved the preference (Cài đặt → Quyền riêng tư), or the
 * API returned it: apply it now, without another request.
 */
export function applyAdMeasurementOptOut(accessToken: string, optedOut: boolean): void {
  decide(accessToken, optedOut ? "blocked" : "allowed");
}

/**
 * Decides for an access token: the seller's saved preference, or "blocked"
 * when it cannot be read (never measure a seller whose choice is unknown).
 */
export function resolveAdMeasurementFor(
  accessToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AdMeasurement> {
  if (decidedFor === accessToken && decision !== "unknown") return Promise.resolve(decision);
  if (pending && pendingFor === accessToken) return pending;
  if (decidedFor !== accessToken && decision !== "unknown") {
    decision = "unknown";
    notify();
  }
  pendingFor = accessToken;
  pending = readOptOut(accessToken, fetchImpl)
    .then((optedOut) => decide(accessToken, optedOut ? "blocked" : "allowed"))
    .catch(() => decide(accessToken, "blocked"))
    .finally(() => {
      if (pendingFor === accessToken) {
        pending = null;
        pendingFor = null;
      }
    });
  return pending;
}

/**
 * Decides for whoever is in this browser now. Signed out → "allowed" with no
 * request, except on `/auth/callback`, where a session is about to land and
 * the answer stays "unknown" until the next decision.
 */
export function resolveAdMeasurement(
  pathname: string,
  fetchImpl: typeof fetch = fetch,
): Promise<AdMeasurement> {
  const session = readAuthSession();
  if (session) return resolveAdMeasurementFor(session.accessToken, fetchImpl);
  if (pathname.startsWith("/auth/callback")) return Promise.resolve("unknown");
  return Promise.resolve(decide("", "allowed"));
}

/** Test seam. */
export function resetAdMeasurement(): void {
  decidedFor = null;
  decision = "unknown";
  pending = null;
  pendingFor = null;
  listeners.clear();
}
