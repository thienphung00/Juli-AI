import { TIKTOK_EVENTS, identifyTikTokUser, trackTikTokEvent } from "@juli/tiktok-events";

import { decodeJwtPayload } from "./supabase-auth";

const REGISTERED_USERS_STORAGE_KEY = "juli_tiktok_registered_users";

interface SupabaseIdentity {
  email: string | null;
  userId: string | null;
}

/**
 * The email and subject claim GoTrue puts in the access token. Read for
 * advanced matching only — exactly as `decodeJwtPayload`'s contract allows,
 * with no signature verification and no authorisation decision resting on it.
 */
export function readSupabaseIdentity(accessToken: string): SupabaseIdentity {
  const payload = decodeJwtPayload(accessToken);

  if (!payload) {
    return { email: null, userId: null };
  }

  return {
    email: typeof payload.email === "string" ? payload.email : null,
    userId: typeof payload.sub === "string" ? payload.sub : null,
  };
}

/**
 * Whether this user has already been counted as a registration, and marking
 * them counted.
 *
 * The Google door has one callback for signing up and for signing back in —
 * GoTrue's token carries no "this identity was just created" claim — so
 * without a guard every return login would report a fresh CompleteRegistration and
 * inflate the conversion TikTok optimises against.
 *
 * Its limits, stated plainly: the record is per browser, so the same person on
 * a second device, or after clearing site data, is counted again. That
 * over-counts a little. Firing on every sign-in would over-count a lot, and
 * TikTok's own deduplication cannot help — those are genuinely distinct
 * conversions as far as it can tell, minutes or weeks apart with no shared
 * event id.
 */
function claimRegistration(userId: string): boolean {
  let counted: string[] = [];

  try {
    const stored = window.localStorage.getItem(REGISTERED_USERS_STORAGE_KEY);
    const parsed: unknown = stored ? JSON.parse(stored) : [];
    counted = Array.isArray(parsed) ? parsed.filter((id) => typeof id === "string") : [];
  } catch {
    // Unreadable or disabled storage: fall through and count this one. A
    // duplicate conversion beats losing every registration on a browser with
    // storage turned off.
    counted = [];
  }

  if (counted.includes(userId)) {
    return false;
  }

  try {
    window.localStorage.setItem(
      REGISTERED_USERS_STORAGE_KEY,
      JSON.stringify([...counted, userId]),
    );
  } catch {
    // Same reasoning: record the event even if we cannot remember it.
  }

  return true;
}

/**
 * Report a completed Google sign-up to TikTok, once per user per browser.
 *
 * `identify` first and `track` second, in that order: identify seeds the
 * matching state the next event reads, it does not decorate events already
 * sent.
 */
export async function reportTikTokRegistration(accessToken: string): Promise<void> {
  if (typeof window === "undefined") {
    return;
  }

  const { email, userId } = readSupabaseIdentity(accessToken);

  if (!userId || !claimRegistration(userId)) {
    return;
  }

  await identifyTikTokUser({ email, externalId: userId });
  trackTikTokEvent(TIKTOK_EVENTS.completeRegistration);
}

export { REGISTERED_USERS_STORAGE_KEY };
