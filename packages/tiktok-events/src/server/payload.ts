import { TIKTOK_DATA_SOURCE_ID, type TikTokEventName, type TikTokEventProperties } from "../data-source";
import type { TikTokHashedIdentity } from "../identity";

/** What the server knows about a relayed event that the browser could not tell it. */
export interface TikTokRequestContext {
  /** True client address. Behind Cloudflare, nginx rewrites this from CF-Connecting-IP. */
  ip?: string;
  /** TikTok's first-party pixel cookie, `_ttp`, read from the request's Cookie header. */
  ttp?: string;
  userAgent?: string;
}

export interface TikTokServerEvent {
  eventId: string;
  eventName: TikTokEventName;
  /** Unix seconds. Set from the server clock — never from the request body. */
  eventTime: number;
  pageUrl?: string;
  properties?: TikTokEventProperties;
  referrer?: string;
  ttclid?: string;
  user?: TikTokHashedIdentity;
}

interface TikTokApiUser extends TikTokHashedIdentity {
  ip?: string;
  ttclid?: string;
  ttp?: string;
  user_agent?: string;
}

export interface TikTokEventsApiPayload {
  data: Array<{
    event: string;
    event_id: string;
    event_time: number;
    page?: { referrer?: string; url?: string };
    properties?: TikTokEventProperties;
    user: TikTokApiUser;
  }>;
  event_source: "web";
  event_source_id: string;
  test_event_code?: string;
}

/**
 * Build one Events API 2.0 request body.
 *
 * Pure, and separated from the HTTP call on purpose — the shape of this
 * payload is the part that is easy to get subtly wrong (a misspelt key is
 * accepted and silently ignored by TikTok, not rejected), so it is worth
 * asserting directly rather than through a mocked fetch.
 */
export function buildTikTokEventPayload(
  event: TikTokServerEvent,
  context: TikTokRequestContext,
  options: { dataSourceId?: string; testEventCode?: string } = {},
): TikTokEventsApiPayload {
  const user: TikTokApiUser = { ...event.user };

  if (context.ip) {
    user.ip = context.ip;
  }
  if (context.userAgent) {
    user.user_agent = context.userAgent;
  }
  if (context.ttp) {
    user.ttp = context.ttp;
  }
  if (event.ttclid) {
    user.ttclid = event.ttclid;
  }

  const page: { referrer?: string; url?: string } = {};
  if (event.pageUrl) {
    page.url = event.pageUrl;
  }
  if (event.referrer) {
    page.referrer = event.referrer;
  }

  const payload: TikTokEventsApiPayload = {
    data: [
      {
        event: event.eventName,
        event_id: event.eventId,
        event_time: event.eventTime,
        ...(page.url || page.referrer ? { page } : {}),
        ...(event.properties && Object.keys(event.properties).length > 0
          ? { properties: event.properties }
          : {}),
        user,
      },
    ],
    event_source: "web",
    event_source_id: options.dataSourceId ?? TIKTOK_DATA_SOURCE_ID,
  };

  if (options.testEventCode) {
    payload.test_event_code = options.testEventCode;
  }

  return payload;
}
