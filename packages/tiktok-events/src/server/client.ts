import type { TikTokEventsApiPayload } from "./payload";

/**
 * Events API 2.0's consolidated endpoint. One endpoint for web, app and
 * offline sources; which one an event belongs to is `event_source` in the
 * body, not a different URL.
 */
export const TIKTOK_EVENTS_API_URL =
  "https://business-api.tiktok.com/open_api/v1.3/event/track/";

/** A slow TikTok must not hold a request open; the event is fire-and-forget. */
const REQUEST_TIMEOUT_MS = 4000;

export type TikTokDeliveryResult =
  | { ok: true }
  | { code?: number; ok: false; reason: string };

/**
 * POST one event to TikTok.
 *
 * TikTok answers HTTP 200 for a rejected event and puts the verdict in the
 * body's `code` field — 0 is success, anything else is not. Checking
 * `response.ok` alone reports every rejection as a success, which is the
 * failure mode where the dashboard looks healthy and no conversion ever
 * arrives. So the body is parsed and `code` is checked.
 */
export async function postTikTokEvent(
  payload: TikTokEventsApiPayload,
  accessToken: string,
  fetchImpl: typeof fetch = fetch,
): Promise<TikTokDeliveryResult> {
  let response: Response;

  try {
    response = await fetchImpl(TIKTOK_EVENTS_API_URL, {
      body: JSON.stringify(payload),
      headers: {
        "Access-Token": accessToken,
        "Content-Type": "application/json",
      },
      method: "POST",
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
  } catch (error) {
    return {
      ok: false,
      reason: error instanceof Error ? error.name : "network error",
    };
  }

  if (!response.ok) {
    return { ok: false, reason: `HTTP ${response.status}` };
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return { ok: false, reason: "unparseable response body" };
  }

  const code = (body as { code?: unknown } | null)?.code;

  if (code === 0) {
    return { ok: true };
  }

  // `message` is TikTok's own description of what it rejected. It describes
  // the payload shape, never the visitor, so it is safe to log.
  const message = (body as { message?: unknown } | null)?.message;

  return {
    code: typeof code === "number" ? code : undefined,
    ok: false,
    reason: typeof message === "string" ? message : "rejected by TikTok",
  };
}
